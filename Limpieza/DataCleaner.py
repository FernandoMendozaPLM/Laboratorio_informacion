"""
cleaners.py
===========
Clases de limpieza optimizadas con Polars.
"""

import os
from abc import ABC, abstractmethod
import polars as pl
from Limpieza.config_clean import MES_A_NOMBRE, MAPEO_PROFESIONES, ESPECIALIDADES_MEDICAS


class BaseDataCleaner(ABC):
    """Clase base abstracta utilizando Polars DataFrames."""

    def __init__(self, df: pl.DataFrame):
        self.df = df

    @abstractmethod
    def clean(self) -> pl.DataFrame:
        pass

    def agregar_month_name(self, columna_mes: str):

        if columna_mes  not in self.df.columns:
            return self.df

        mapeo_str = {str(k): str(v) for k, v in MES_A_NOMBRE.items()}

        return self.df.with_columns(
            pl.col(columna_mes)
            .cast(pl.String)
            .replace_strict(
                mapeo_str,
                default=pl.col(columna_mes).cast(pl.String) # Mantener el valor original si no hace match
            )
        )

    def agregar_total(self, columna_clics:str = 'Clics', columna_prints:str = 'Prints', alias_total:str = 'Total') -> 'BaseDataCleaner':

        if columna_clics in self.df.columns and columna_prints in self.df.columns:
            self.df = self.df.with_columns((
                    pl.col(columna_clics).cast(pl.Int64, strict=False).fill_null(0) +
                    pl.col(columna_prints).cast(pl.Int64, strict=False).fill_null(0)
                ).alias(alias_total))
        return self

    def limpiar_agp_especialidad(self, columna_profesion: str, columna_especialidad: str) -> 'BaseDataCleaner':
        """Aplica reglas de negocio vectorizadas mediante pl.when().then().otherwise()."""
        
        # 1. Crear columna AGP si no existe usando mapeo
        if 'AGP' not in self.df.columns and columna_profesion in self.df.columns:
            self.df = self.df.with_columns(
                pl.col(columna_profesion).replace(MAPEO_PROFESIONES).alias('AGP')
            )

        # 2. Aplicar Reglas de Negocio en AGP
        # Regla 1: AGP y Esp nulos -> 'OTRAS PROFESIONES'
        # Regla 2: AGP nulo + Esp en lista médica -> 'MÉDICO'
        # Regla 3: AGP nulo -> 'NO ESPECIFICADA'
        self.df = self.df.with_columns(
            pl.when(pl.col('AGP').is_null() & pl.col(columna_especialidad).is_null())
            .then(pl.lit('OTRAS PROFESIONES'))
            .when(pl.col('AGP').is_null() & pl.col(columna_especialidad).is_in(ESPECIALIDADES_MEDICAS))
            .then(pl.lit('MÉDICO'))
            .when(pl.col('AGP').is_null())
            .then(pl.lit('NO ESPECIFICADA'))
            .otherwise(pl.col('AGP'))
            .alias('AGP')
        )

        # 3. Aplicar Reglas de Negocio en Especialidad
        # Regla 4: AGP = 'MÉDICO' y Esp nula -> 'MEDICINA GENERAL'
        # Regla 5: AGP = 'MÉDICO' y Esp = 'OTRA' -> 'MEDICINA GENERAL'
        self.df = self.df.with_columns(
            pl.when((pl.col('AGP') == 'MÉDICO') & (pl.col(columna_especialidad).is_null() | (pl.col(columna_especialidad) == 'OTRA')))
            .then(pl.lit('MEDICINA GENERAL'))
            .otherwise(pl.col(columna_especialidad))
            .alias(columna_especialidad)
        )

        return self

    def fill_na_with_nulls(self) -> 'BaseDataCleaner': #Remplaza valores nulos con la cadena 'NULL'
        self.df = self.df.with_columns(
            pl.when(pl.col(pl.Utf8).str.strip_chars() == "")
            .then(None)
            .otherwise(pl.col(pl.Utf8))
            .fill_null('NULL')
            .name.keep()
        )
        return self

    #método usado por el formato entregado en el reporteador, para identificar correctamente
    #el nombre de las columnas y trabajarlas correctamente
    def nombrar_columnas(self):

        mapping = {}
        for i, col in enumerate(self.df.columns):
            mapping[col] = self.df[0,i]
        
        self.df = self.df.rename(mapping)

        return self   


class AppDataCleaner(BaseDataCleaner):



    def clean(self) -> pl.DataFrame:

        # 1. Polars por defecto pasa de largo a columnas vacías por lo que no es necesario eliminar las nulas´
        #sin embargo la estructura de lectura requiere identificar las columnas dadas en el formato
        #ClientId, por lo que es necesario en ese caso agregar el uso de df_raw = nombrar_columnas(df_raw)
        #para renombrar las columnas y poder trabajar con ellas

        self.nombrar_columnas()

        # 2. Mapear y limpiar AGP / Especialidad
        self.limpiar_agp_especialidad(columna_profesion='Profesión', columna_especialidad='Especialidad')

        # 3. Nombre de mes
        self.agregar_month_name('Mes')

        # 4. Rellenar con 'NULL'
        self.fill_na_with_nulls()

        print(f"DATA-APP procesada exitosamente: {self.df.shape}")
        return self.df


class WebDataCleaner(BaseDataCleaner):
    """Limpiador de datos WEB con expresiones Regex de Polars."""

    def __init__(self, df: pl.DataFrame, catalogo_path: str):
        super().__init__(df)
        self.catalogo_path = catalogo_path

    def clean(self) -> pl.DataFrame:
        print("  Procesando DATA-WEB...")
        col_time = 'Fecha y hora (AAAAMMDDHH)'
        col_ruta = 'Ruta de página y clase de pantalla'

        # 1. Extraer Fecha y Hora
        if col_time in self.df.columns:
        # Parsear string a DateTime
            self.df = self.df.with_columns(
                (pl.col(col_time).cast(pl.Utf8).str.zfill(10) + "00")
                .str.to_datetime('%Y%m%d%H%M', strict=False)
                .alias('dt_temp')
            ).with_columns([
                pl.col('dt_temp').dt.year().alias('año'),
                pl.col('dt_temp').dt.month().alias('mes')
            ]).drop('dt_temp')
        else:
            self.df = self.df.with_columns([
                pl.lit(None).cast(pl.Int32).alias('año'),
                pl.lit(None).cast(pl.Int32).alias('mes')
            ])

        if col_ruta not in self.df.columns:
            return self.df



        # 2. Extraer fragmento usando expresiones regulares vectorizadas
        regex_split = r"(?i)/productos/(.*)"
        self.df = self.df.with_columns(
            pl.col(col_ruta).str.extract(regex_split, 1).alias('data_web')
        )

        # 3. Separar por slashes '/' la estructura de catálogo (CAT/LAB/PROD/FF)
        self.df = self.df.with_columns([
            pl.col('data_web').str.split('/').list.get(0, null_on_oob=True).alias('CAT'),
            pl.col('data_web').str.split('/').list.get(1, null_on_oob=True).alias('LAB'),
            pl.col('data_web').str.split('/').list.get(2, null_on_oob=True).alias('PROD'),
            pl.col('data_web').str.split('/').list.get(3, null_on_oob=True).alias('FF'),
        ])


        # Reconstruir la ruta base
        self.df = self.df.with_columns(
            (pl.col(col_ruta).str.split_exact('/productos/', 1).struct.field('field_0') + '/productos/').alias(col_ruta)
        )


        # 4. Mapear Catálogo (mediante un JOIN de Polars)
        if os.path.exists(self.catalogo_path):
            try:
                # Leer catálogo
                df_cat = pl.read_excel(self.catalogo_path) if self.catalogo_path.endswith('.xlsx') else pl.read_csv(self.catalogo_path)
                
                df_cat = df_cat.select([
                    pl.col('ProductId').cast(pl.Utf8).str.strip_chars().alias('PROD_key'),
                    pl.col('Brand').alias('PRODUCTO')
                ]).unique(subset=['PROD_key'])

                self.df = self.df.with_columns(pl.col('PROD').cast(pl.Utf8).str.strip_chars().alias('PROD_key'))
                
                # Left join
                self.df = self.df.join(df_cat, on='PROD_key', how='left').drop('PROD_key')

            except Exception as e:
                print(f"    Error al cruzar catálogo: {e}")
                self.df = self.df.with_columns(pl.lit('NULL').alias('PRODUCTO'))

        else:
            self.df = self.df.with_columns(pl.lit('NULL').alias('PRODUCTO'))

        # 5. Agregar Mes y Cast Numéricos
        self.agregar_month_name('mes')

        cols_num = ['CAT', 'LAB', 'PROD', 'FF', 'Usuarios activos', 'Número de eventos']
        for c in cols_num:
            if c in self.df.columns:
                self.df = self.df.with_columns(pl.col(c).cast(pl.Int64, strict=False))

        # 6. Rellenar nulos
        self.fill_na_with_nulls()

        print(f"DATA-WEB procesada exitosamente: {self.df.shape}")
        return self.df


class RadDataCleaner(BaseDataCleaner):
    """Limpiador de datos de Radiografía en Polars."""

    def clean(self) -> pl.DataFrame:
        print("  Procesando DATA-RAD...")

        # 1 y 2. Mapear y limpiar AGP / Especialidad con nombres de columna de RAD
        self.limpiar_agp_especialidad(columna_profesion='ProfessionName', columna_especialidad='SpecialityName')

        # 3. Mes
        self.agregar_month_name('Mes')

        # 4. Calcular Total en Polars
        if 'Clics' in self.df.columns and 'Prints' in self.df.columns:
            self.df = self.df.with_columns(
                (
                    pl.col('Clics').cast(pl.Float64, strict=False).fill_null(0) +
                    pl.col('Prints').cast(pl.Float64, strict=False).fill_null(0)
                ).alias('Total')
            )

        # 5. Rellenar nulos
        self.fill_na_with_nulls()

        print(f"DATA-RAD procesada exitosamente: {self.df.shape}")
        return self.df

