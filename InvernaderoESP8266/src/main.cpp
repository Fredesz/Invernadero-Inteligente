#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include "credenciales.h"

WiFiClient red;
PubSubClient mqtt(red);

constexpr unsigned long DURACION_VENTANA = 300000;
constexpr int MEDICIONES = 15;
constexpr unsigned long TRAMO = DURACION_VENTANA / MEDICIONES;
constexpr int MUESTRAS_ADC = 51;
constexpr unsigned long INTERVALO_RECONEXION = 5000;

unsigned long inicioVentana;
unsigned long ultimoIntentoMqtt;
int ultimoTramo = -1;
int medicionesTomadas = 0;
int medianas[MEDICIONES];
long sumaVentana = 0;
int minimoVentana;
int maximoVentana;

void ordenar(int* valores, int cantidad) {
    for (int i = 1; i < cantidad; ++i) {
        const int actual = valores[i];
        int j = i;
        while (j > 0 && valores[j - 1] > actual) {
            valores[j] = valores[j - 1];
            --j;
        }
        valores[j] = actual;
    }
}

void medir() {
    int lecturas[MUESTRAS_ADC];
    for (int i = 0; i < MUESTRAS_ADC; ++i) {
        lecturas[i] = analogRead(A0);
        sumaVentana += lecturas[i];
        delay(20);
    }

    ordenar(lecturas, MUESTRAS_ADC);
    medianas[medicionesTomadas] = lecturas[MUESTRAS_ADC / 2];
    if (medicionesTomadas == 0 || lecturas[0] < minimoVentana) {
        minimoVentana = lecturas[0];
    }
    if (medicionesTomadas == 0 || lecturas[MUESTRAS_ADC - 1] > maximoVentana) {
        maximoVentana = lecturas[MUESTRAS_ADC - 1];
    }
    ++medicionesTomadas;
    Serial.printf("Mediciones de la ventana: %d/%d\n", medicionesTomadas, MEDICIONES);
}

void publicarVentana() {
    if (medicionesTomadas != MEDICIONES) {
        Serial.printf("Ventana incompleta: %d/%d mediciones.\n", medicionesTomadas, MEDICIONES);
        return;
    }

    ordenar(medianas, MEDICIONES);
    const double promedio = sumaVentana / static_cast<double>(MEDICIONES * MUESTRAS_ADC);
    char mensaje[160];
    const int longitud = snprintf(
        mensaje, sizeof(mensaje),
        "{\"cantidad_mediciones\":%d,\"promedio\":%.3f,\"mediana\":%d,"
        "\"minimo\":%d,\"maximo\":%d,\"rango\":%d}",
        MEDICIONES, promedio, medianas[MEDICIONES / 2],
        minimoVentana, maximoVentana, maximoVentana - minimoVentana
    );
    if (longitud > 0 && longitud < static_cast<int>(sizeof(mensaje)) &&
        mqtt.publish("invernadero/suelo/resumen", mensaje)) {
        Serial.println(mensaje);
    } else {
        Serial.println("No se pudo publicar el resumen.");
    }
}

void mantenerMqtt(unsigned long ahora) {
    if (WiFi.status() != WL_CONNECTED) {
        return;
    }
    if (mqtt.connected()) {
        mqtt.loop();
        return;
    }
    if (ahora - ultimoIntentoMqtt >= INTERVALO_RECONEXION) {
        ultimoIntentoMqtt = ahora;
        if (mqtt.connect("invernadero-nodemcu", "nodemcu", MQTT_CLAVE)) {
            Serial.println("Conectado a Mosquitto.");
        } else {
            Serial.printf("Error MQTT: %d\n", mqtt.state());
        }
    }
}

void setup() {
    Serial.begin(115200);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_CLAVE);
    mqtt.setServer("192.168.1.41", 1884);
    mqtt.setSocketTimeout(2);
    inicioVentana = millis();
    ultimoIntentoMqtt = inicioVentana - INTERVALO_RECONEXION;
}

void loop() {
    const unsigned long ahora = millis();
    mantenerMqtt(ahora);
    unsigned long transcurrido = millis() - inicioVentana;

    if (transcurrido >= DURACION_VENTANA) {
        publicarVentana();
        inicioVentana += (transcurrido / DURACION_VENTANA) * DURACION_VENTANA;
        ultimoTramo = -1;
        medicionesTomadas = 0;
        sumaVentana = 0;
        transcurrido = millis() - inicioVentana;
    }

    const int tramoActual = transcurrido / TRAMO;
    if (tramoActual != ultimoTramo) {
        ultimoTramo = tramoActual;
        medir();
    }
    delay(10);
}
