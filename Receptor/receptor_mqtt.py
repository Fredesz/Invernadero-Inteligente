import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from getpass import getpass

import paho.mqtt.client as mqtt
import psycopg


TEMA = "invernadero/suelo/resumen"
DURACION_VENTANA = timedelta(minutes=5)
INSERTAR = """
    INSERT INTO public.humedad_suelo (
        inicio_ventana, fin_ventana, cantidad_mediciones,
        promedio, mediana, minimo, maximo
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id, rango
"""


def interpretar(payload):
    datos = json.loads(payload, parse_float=Decimal)
    if not isinstance(datos, dict):
        raise ValueError("El mensaje debe ser un objeto JSON.")

    cantidad = datos["cantidad_mediciones"]
    promedio = datos["promedio"]
    mediana = datos["mediana"]
    minimo = datos["minimo"]
    maximo = datos["maximo"]
    rango = datos["rango"]

    if type(cantidad) is not int or cantidad != 15:
        raise ValueError("Se esperaban 15 mediciones.")
    if any(type(valor) is not int for valor in (mediana, minimo, maximo, rango)):
        raise ValueError("Mediana, mínimo, máximo y rango deben ser enteros.")
    if type(promedio) not in (int, Decimal):
        raise ValueError("El promedio debe ser numérico y finito.")
    if isinstance(promedio, Decimal) and not promedio.is_finite():
        raise ValueError("El promedio debe ser finito.")
    if not (
        0 <= minimo <= mediana <= maximo <= 1023
        and minimo <= promedio <= maximo
        and rango == maximo - minimo
    ):
        raise ValueError("Las estadísticas del mensaje son incoherentes.")

    return cantidad, promedio, mediana, minimo, maximo


def al_conectar(cliente, contexto, indicadores, motivo, propiedades):
    if motivo.is_failure:
        logging.error("Mosquitto rechazó la conexión: %s", motivo)
        return
    cliente.subscribe(TEMA)


def al_suscribir(cliente, contexto, identificador, motivos, propiedades):
    if any(motivo.is_failure for motivo in motivos):
        logging.error("Mosquitto rechazó la suscripción a %s", TEMA)
    else:
        logging.info("Suscrito a %s. Esperando mediciones reales.", TEMA)


def al_recibir(cliente, opciones_db, mensaje):
    fin = datetime.now(timezone.utc)
    try:
        estadisticas = interpretar(mensaje.payload)
    except (KeyError, ValueError) as error:
        logging.warning("Mensaje MQTT descartado: %s", error)
        return

    try:
        with psycopg.connect(**opciones_db) as conexion:
            fila_id, rango = conexion.execute(
                INSERTAR, (fin - DURACION_VENTANA, fin, *estadisticas)
            ).fetchone()
    except psycopg.Error as error:
        logging.error("No se pudo guardar el resumen en PostgreSQL: %s", error)
        return
    logging.info("Fila %s guardada. Promedio: %s | Rango: %s", fila_id, estadisticas[1], rango)


def main():
    parser = argparse.ArgumentParser(description="Guarda resúmenes MQTT en PostgreSQL.")
    parser.add_argument("--broker", default="192.168.1.41")
    parser.add_argument("--puerto-mqtt", type=int, default=1884)
    parser.add_argument("--usuario-mqtt", default="nodemcu")
    parser.add_argument("--servidor-db", default="localhost")
    parser.add_argument("--puerto-db", type=int, default=5432)
    parser.add_argument("--base", default="Invernadero")
    parser.add_argument("--usuario-db", default="postgres")
    parser.add_argument("--log", help="Archivo opcional para el registro del receptor.")
    args = parser.parse_args()

    handlers = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers
    )
    opciones_db = {
        "host": args.servidor_db,
        "port": args.puerto_db,
        "dbname": args.base,
        "user": args.usuario_db,
        "password": getpass("Contraseña PostgreSQL: "),
        "connect_timeout": 5,
    }
    try:
        with psycopg.connect(**opciones_db) as conexion:
            conexion.execute("SELECT id FROM public.humedad_suelo LIMIT 0")
    except psycopg.Error as error:
        parser.exit(1, f"Error al abrir la tabla en PostgreSQL: {error}\n")
    logging.info("Conexión a PostgreSQL comprobada.")

    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=opciones_db)
    cliente.username_pw_set(args.usuario_mqtt, getpass("Contraseña MQTT: "))
    cliente.on_connect = al_conectar
    cliente.on_subscribe = al_suscribir
    cliente.on_message = al_recibir
    try:
        cliente.connect_async(args.broker, args.puerto_mqtt, keepalive=30)
        cliente.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        logging.info("Receptor detenido.")
    finally:
        cliente.disconnect()


if __name__ == "__main__":
    main()
