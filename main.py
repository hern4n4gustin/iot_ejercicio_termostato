# Resolución ejercicio termostato
# IoT - 2026

from mqtt_as import MQTTClient
from mqtt_local import config
import uasyncio as asyncio
import dht, machine, ujson, binascii

# Defnino los pines para comandar el circuito del relé:
# Pin para la recepción de datos
PIN_DHT = 15
# Pin para activar el re;é
PIN_RELE = 16 

# Creo el objeto sensor y le paso el pin correspondiente
sensor = dht.DHT22(machine.Pin(PIN_DHT))

# Objeto para controlar el pin de activacioón del relé
rele = machine.Pin(PIN_RELE, machine.Pin.OUT, value=1)

# Lvariable para el led de la placa
led = machine.Pin("LED", machine.Pin.OUT)

# Tomo la MAC de la placa, lo paso a hexadecimal y luego a str
ID_PLACA = binascii.hexlify(machine.unique_id()).decode()

# Diccionario para guardar el estado del termostato
#   - El modo puede ser "auto" o "manual"
state = {"setpoint": 25.0, "periodo": 10, "modo": "auto", "rele": 0}

# =========================
# PERSISTENCIA
# =========================

# Función para guardar el estado del relé en memoria, luego se puede cargar y leerlo.
def guardar_estado():

    # Manejo de error por si falla la apertura o guardado del estado
    try:
        # Abro el archivo en formato escritura y, si no existe, se crea
        with open("estado.json", "w") as archivo:
            # Guardo el estado actual (state) en el archivo en formato JSON
            ujson.dump(state, archivo)
    # Si hay un error, lo imprime en pantalla
    except Exception as error:
        print("Error guardando:", error)


# Función par cargar el estado 
def cargar_estado():

    # Tomo la variable global
    global state

    # Manejo de errores
    try:
        # Abro el archivo que contiene el estado, generado por la funcion guardar_estado()
        # Se abre en formato lectura
        with open("estado.json", "r") as archivo:
            # Leo el archivo y se guarda en formato diccionario
            datos = ujson.load(archivo)
            # Actualizo la variable state solo con las claves que están en el archivo leído
            state.update(datos)
        print("Estado cargado:", state)
    # Error de lectura de archivo
    except OSError:
        print("No existe estado, creando...")
        # Como no había un archivo de estado, ahora se crea de igual maera
        guardar_estado()

# Función asíncrona para hacer parpadear el LED de la placa
async def destello():
    
    # Tango de 6 iteraciones
    for i in range(6):
        
        # Cambia el estado del LED
        led.toggle()

        # Await para ceder el control
        await asyncio.sleep_ms(300)
    
    # Apaga el LED
    led.off()


# Función para publicar en un tópico, se le pasa el cliente MQTT
async def enviar_broker(client):
    while True:
        try:
            # Se genera la medición y se guardan en los atributos del objeto sensor
            sensor.measure()

            # Leo los valores actualizados y los guardo en 2 variables
            temp = sensor.temperature()
            hum = sensor.humidity()

            # Actualiza el valor de la temperatura en el estado del sistema
            state["temp_actual"] = temp

            # Variable para guardar los datos a publicar
            publicacion = {
                # Los primeros 2 son los leídos
                "temperatura": temp,
                "humedad": hum,

                # Los siguientes son los guardados en el diccionario de estado
                "setpoint": state["setpoint"],
                "periodo": state["periodo"],
                "modo": state["modo"]}

            # Información en consola
            print("Publicando:", publicacion)

            # Se envía el mensaje por MQTT a el tópico de la placa
            await client.publish(ID_PLACA, ujson.dumps(publicacion), qos=1)

        # Imprimo e nconsola si hay error
        except OSError:
            print("Error sensor")

        # Sleep asíncrono que depende del tiempo indicado en periodo, es decir, el
        # tiempo mínimo entre envío y envío.
        await asyncio.sleep(state["periodo"])


# Función que recibe datos desde MQTT
async def recibir_broker(client):

    # Para recorrer cada vez que llega un mensaje nuevo (.queue es la cola de mensajes recibidos)
    async for topic, msg, retained in client.queue:
        try:
            # Decodifico a str los bytes de MQTT
            t = topic.decode()
            m = msg.decode()    

            print("Recibido:", t, "->", m)

            # El procesamiento del mensaje es diferente, depende del tópico:
            # Tópico setpoint
            if t.endswith("/setpoint"):
                # Paso el número a float y lo almaceno en la variable global de estado
                state["setpoint"] = float(m)
                # Llamo a la función para guardar en la memoria
                guardar_estado()


            # Tópico periodo
            elif t.endswith("/periodo"):
                # Paso el número a int y lo almaceno en la variable global de estado
                state["periodo"] = int(m)
                # Llamo a la función para guardar en la memoria
                guardar_estado()

            # Tópico modo
            elif t.endswith("/modo"):
                # Toma el valor str del mensaje que lelga y lo guardo en la variable global de estado
                # Puede ser "auto" o "manual"
                state["modo"] = m
                # Llamo a la función para guardar en la memoria
                guardar_estado()

            # Tópico relé (solo funciona si está en modo "manual")
            elif t.endswith("/rele"):
                # Verifico que esté en modo manual
                if state["modo"] == "manual":
                    # Paso el número a int y lo almaceno en la variable global de estado
                    state["rele"] = int(m)
                    # Llamo a la función para guardar en la memoria
                    guardar_estado()

            # Tópico destello
            elif t.endswith("/destello"):
                # Uso la función asíncrona destello (no bloqueo el programa)
                asyncio.create_task(destello())

        # Imprimo en consola si hay un error
        except Exception as e:
            print("Error de Recepción:", e)


# Función para controlar el relé
async def control_rele():

    # Bucle infinito para que se ejecute constantemente
    while True:
        # Leo el estado actual del modo del sistema
        modo_actual = state["modo"]
        # Leo la temperatura pero puede ocurrir 2 cosas:
        #   - Si ya hay medición hecha, uso la temperatura actual "temp_actual" (se crea al publicar)
        #   - Si aún no la hay, uso el setpoint como valor seguro
        temp = state.get("temp_actual", state["setpoint"])

        # Modo automático (el sistema tiene que decidirs olo)
        if modo_actual == "auto":
            # Si la temperatura es mayor al setpoint, debe activarse
            if temp > state["setpoint"]:
                # Pongo la salida del pin en 0, ya que el relé es activo en bajo
                rele.value(0)
                # Actualizo el estado lógico (1 significa encendido)
                state["rele"] = 1
            # Si la temperatura es menor al setpoint, debe apagarse el relé
            else:
                # Pongo la salida el pin en 1, ya que el relé se desactiva en alto
                rele.value(1)  # OFF
                # Actualizo el estado lógico (0 significa apagado)
                state["rele"] = 0

        # Modo manual (el usuario elige)
        elif modo_actual == "manual":
            # Si el estado del relé es 1, debe activarse
            if state["rele"] == 1:
                # Pongo la salida del pin en 0 (activo el relé)
                rele.value(0)
            # Si el estado del relé es 0, debe desactivarse
            else:
                # Pongo la salida del pin en 1 (apago el relé)
                rele.value(1)

        # Espero 1 segundo antes de volver a actualizar el control del relé
        await asyncio.sleep(1)


# Función para conectarse a los tópicos
async def conexion_topicos(client):
    # Lista con los subtopicos a escuchar
    topicos = ["/setpoint", "/periodo", "/modo", "/rele", "/destello"]

    # Bucle infinito (para reconexiones por si se corta el WiFi y se pierden las suscripciones)
    while True:
        # Se espera hasta el que esté conectado
        await client.up.wait()
        # Reinicio el evento para la próxima reconexión
        client.up.clear()
        
        # Recorro cada uno de los subtópicos
        for t in topicos:
            # Construyo el tópico
            topico = ID_PLACA + t
            # Suscripción al tópico correspondiente
            await client.subscribe(topico, qos=1)
            # Imprimo en consola a cuál tópico se está suscripto
            print("Suscrito a:", topico)


# Función main
async def main(client):
    # Se espera hasta conectar el cliente al broker MQTT
    await client.connect()
    # Espera de 2 segundos para que todo se estabilice
    await asyncio.sleep(2)

    # Se generan las corrutinas correspondientes:
    # Suscripción a MQTT:
    asyncio.create_task(conexion_topicos(client))
    
    # Publicación de datos al broker:
    asyncio.create_task(enviar_broker(client))
    
    # Escucha de mensajes del broker:
    asyncio.create_task(recibir_broker(client))
    
    # Encendido/apagado del relé
    asyncio.create_task(control_rele())

    # Bucle para mantener funcionando el programa
    while True:
        await asyncio.sleep(60)


# Activo MQTTS
config['ssl'] = True

# Longitud de la cola de mensajes recibidos
config['queue_len'] = 4

# Leo el archvio de estado de la memoria
cargar_estado()

MQTTClient.DEBUG = True

# Crea el cliente MQTT con la configuración predefinida
client = MQTTClient(config)

# Inicio el bucle async
try:
    # El main se ejecuta y se lanzan todas las tareas
    asyncio.run(main(client))
finally:
    # Cierro la conexión con el broker
    client.close()
    # Apago el relé
    rele.value(1)
    # Limpieza del loop asyncio
    asyncio.new_event_loop()