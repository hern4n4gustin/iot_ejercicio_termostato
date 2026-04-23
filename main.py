# Germán Andrés Xander 2024

from mqtt_as import MQTTClient
from mqtt_local import config
import uasyncio as asyncio
import dht, machine, ujson, binascii

# =========================
# HARDWARE
# =========================

PIN_DHT = 15      # --> DATA del DHT22
PIN_RELE = 16     # --> IN del relé (activo en bajo)

sensor = dht.DHT22(machine.Pin(PIN_DHT))
rele = machine.Pin(PIN_RELE, machine.Pin.OUT, value=1)

# LED onboard (opcional para destello)
led = machine.Pin("LED", machine.Pin.OUT)

# =========================
# ID ÚNICO DEL DISPOSITIVO
# =========================

DEVICE_ID = binascii.hexlify(machine.unique_id()).decode()

# =========================
# ESTADO DEL SISTEMA
# =========================

estado = {
    "setpoint": 25.0,
    "periodo": 10,
    "modo": "automatico",   # "automatico" o "manual"
    "rele": 0               # estado lógico
}

# =========================
# PERSISTENCIA
# =========================

def guardar_estado():
    try:
        with open("estado.json", "w") as f:
            ujson.dump(estado, f)
    except Exception as e:
        print("Error guardando:", e)

def cargar_estado():
    global estado
    try:
        with open("estado.json", "r") as f:
            datos = ujson.load(f)
            estado.update(datos)
        print("Estado cargado:", estado)
    except OSError:
        print("No existe estado, creando...")
        guardar_estado()

# =========================
# DESTELLO (EVENTO)
# =========================

async def destello():
    for _ in range(6):
        led.toggle()
        await asyncio.sleep_ms(300)
    led.off()

# =========================
# PUBLICACIÓN
# =========================

async def tarea_publicar(client):
    while True:
        try:
            sensor.measure()
            temp = sensor.temperature()
            hum = sensor.humidity()

            estado["temp_actual"] = temp

            payload = {
                "temperatura": temp,
                "humedad": hum,
                "setpoint": estado["setpoint"],
                "periodo": estado["periodo"],
                "modo": estado["modo"]
            }

            print("Publicando:", payload)

            await client.publish(
                DEVICE_ID,
                ujson.dumps(payload),
                qos=1
            )

        except OSError:
            print("Error sensor")

        await asyncio.sleep(estado["periodo"])

# =========================
# RECEPCIÓN (EVENTOS)
# =========================

async def tarea_escucha(client):
    async for topic, msg, retained in client.queue:
        try:
            t = topic.decode()
            m = msg.decode()

            print("RX:", t, "->", m)

            if t.endswith("/setpoint"):
                estado["setpoint"] = float(m)
                guardar_estado()

            elif t.endswith("/periodo"):
                estado["periodo"] = int(m)
                guardar_estado()

            elif t.endswith("/modo"):
                estado["modo"] = m
                guardar_estado()

            elif t.endswith("/rele"):
                if estado["modo"] == "manual":
                    estado["rele"] = int(m)
                    guardar_estado()

            elif t.endswith("/destello"):
                asyncio.create_task(destello())

        except Exception as e:
            print("Error RX:", e)

# =========================
# CONTROL DEL RELÉ
# =========================

async def tarea_control():
    while True:
        modo = estado["modo"]
        temp = estado.get("temp_actual", estado["setpoint"])

        if modo == "automatico":
            if temp > estado["setpoint"]:
                rele.value(0)  # ON (activo bajo)
                estado["rele"] = 1
            else:
                rele.value(1)  # OFF
                estado["rele"] = 0

        elif modo == "manual":
            if estado["rele"] == 1:
                rele.value(0)
            else:
                rele.value(1)

        await asyncio.sleep(1)

# =========================
# SUSCRIPCIONES
# =========================

async def tarea_conexion(client):
    topicos = ["/setpoint", "/periodo", "/modo", "/rele", "/destello"]

    while True:
        await client.up.wait()
        client.up.clear()

        for t in topicos:
            topico = DEVICE_ID + t
            await client.subscribe(topico, qos=1)
            print("Suscrito a:", topico)

# =========================
# MAIN
# =========================

async def main(client):
    await client.connect()
    await asyncio.sleep(2)

    asyncio.create_task(tarea_conexion(client))
    asyncio.create_task(tarea_publicar(client))
    asyncio.create_task(tarea_escucha(client))
    asyncio.create_task(tarea_control())

    while True:
        await asyncio.sleep(60)

# =========================
# CONFIGURACIÓN MQTT
# =========================

config['ssl'] = True
config['queue_len'] = 5  # mejor que 1

# =========================
# INICIO
# =========================

cargar_estado()

MQTTClient.DEBUG = True
client = MQTTClient(config)

try:
    asyncio.run(main(client))
finally:
    client.close()
    rele.value(1)
    asyncio.new_event_loop()