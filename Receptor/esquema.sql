CREATE TABLE public.humedad_suelo (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inicio_ventana timestamptz NOT NULL,
    fin_ventana timestamptz NOT NULL,
    cantidad_mediciones integer NOT NULL CHECK (cantidad_mediciones > 0),
    promedio numeric NOT NULL,
    mediana numeric NOT NULL,
    minimo integer NOT NULL,
    maximo integer NOT NULL,
    rango integer GENERATED ALWAYS AS (maximo - minimo) STORED,
    CHECK (fin_ventana > inicio_ventana),
    CHECK (maximo >= minimo)
);
