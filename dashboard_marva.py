"""
Dashboard de Piso - Marva Silos y Construcción
================================================
Conecta con Odoo vía XML-RPC (sin necesidad de módulos extra en Odoo)
y muestra en tiempo real lo que se está fabricando, avances, centros
de trabajo, horas y una vista de calidad.

Uso:
    1. Instala dependencias:
       pip install streamlit pandas plotly

    2. Configura tus credenciales (ver sección CONFIGURACIÓN abajo,
       o mejor, crea un archivo .streamlit/secrets.toml con:

            ODOO_URL = "https://marva.odoo.com"
            ODOO_DB = "marva"
            ODOO_USER = "usuario@marva.com"
            ODOO_PASSWORD = "tu_password_o_api_key"

    3. Corre la app:
       streamlit run dashboard_marva.py
"""

import base64
import json
import threading
import xmlrpc.client
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ============================================================
# IDENTIDAD VISUAL — Marva Silos y Construcción
# ============================================================
# Logo y favicon oficiales, tomados de marvasilos.com
LOGO_URL = "https://marvasilos.com/wp-content/uploads/2024/06/Logo.svg"
FAVICON_URL = "https://marvasilos.com/wp-content/uploads/2024/06/cropped-Favicon-270x270.png"

# Paleta clara: fondo blanco/gris-azulado + azul acero como acento.
# Si tienes los códigos de color oficiales de Marva, dímelos y los pongo exactos.
COLOR_PRIMARIO = "#16537E"      # azul acero — acentos, botones, KPIs destacados
COLOR_FONDO = "#F5F8FA"         # blanco grisáceo — fondo principal
COLOR_FONDO_SEC = "#E7EEF4"     # gris-azulado claro — tarjetas, contenedores
COLOR_TEXTO = "#1B2B3A"         # azul marino oscuro — texto principal (buen contraste en claro)
COLOR_BORDE = "#D3DFE8"         # gris-azulado — bordes y líneas de cuadrícula
COLOR_TEXTO_SUAVE = "#5A7A94"   # azul grisáceo — texto secundario, etiquetas

# ============================================================
# CONFIGURACIÓN
# ============================================================
st.set_page_config(
    page_title="Dashboard de Piso · Marva Silos y Construcción",
    layout="wide",
    page_icon=FAVICON_URL,
)

st.markdown(f"""
<style>
    .stApp {{
        background-color: {COLOR_FONDO};
        color: {COLOR_TEXTO};
    }}
    /* Encabezado con logo */
    .marva-header {{
        display: flex;
        align-items: center;
        gap: 20px;
        padding: 18px 24px;
        background: linear-gradient(90deg, {COLOR_FONDO_SEC} 0%, {COLOR_FONDO} 100%);
        border-radius: 12px;
        border-left: 5px solid {COLOR_PRIMARIO};
        margin-bottom: 20px;
    }}
    .marva-header img {{ height: 42px; }}
    .marva-header .titulo {{ font-size: 1.5rem; font-weight: 700; color: {COLOR_TEXTO}; margin: 0; }}
    .marva-header .subtitulo {{ font-size: 0.85rem; color: {COLOR_TEXTO_SUAVE}; margin: 0; }}

    /* Tarjetas de KPI */
    div[data-testid="stMetric"] {{
        background-color: {COLOR_FONDO_SEC};
        border: 1px solid {COLOR_BORDE};
        border-left: 4px solid {COLOR_PRIMARIO};
        border-radius: 10px;
        padding: 14px 16px 8px 16px;
    }}
    div[data-testid="stMetric"] label {{ color: {COLOR_TEXTO_SUAVE} !important; }}
    div[data-testid="stMetricValue"] {{ color: {COLOR_TEXTO} !important; }}

    /* Pestañas */
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background-color: {COLOR_FONDO_SEC};
        border-radius: 8px 8px 0 0;
        padding: 8px 16px;
        color: {COLOR_TEXTO_SUAVE};
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {COLOR_PRIMARIO} !important;
        color: {COLOR_FONDO} !important;
        font-weight: 600;
    }}

    /* Botones */
    .stButton button {{
        background-color: {COLOR_PRIMARIO};
        color: {COLOR_FONDO};
        border: none;
        font-weight: 600;
    }}
    .stButton button:hover {{ opacity: 0.85; color: {COLOR_FONDO}; }}

    /* Tablas */
    div[data-testid="stDataFrame"] {{ border: 1px solid {COLOR_BORDE}; border-radius: 8px; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="marva-header">
    <img src="{LOGO_URL}" alt="Marva Silos y Construcción">
    <div>
        <p class="titulo">Dashboard de Piso — Fabricación</p>
        <p class="subtitulo">Marva Silos y Construcción · Datos en vivo desde Odoo</p>
    </div>
</div>
""", unsafe_allow_html=True)

def _get_config(key, default=""):
    """Busca primero en st.secrets, si no existe usa el default de abajo."""
    try:
        return st.secrets[key]
    except Exception:
        return default

ODOO_URL = _get_config("ODOO_URL", "https://marva.odoo.com")
ODOO_DB = _get_config("ODOO_DB", "marva")
ODOO_USER = _get_config("ODOO_USER", "usuario@marva.com")
ODOO_PASSWORD = _get_config("ODOO_PASSWORD", "")


# ============================================================
# CONEXIÓN A ODOO
# ============================================================
@st.cache_resource(show_spinner="Conectando con Odoo...")
def _autenticar_odoo():
    """Solo el uid se comparte entre sesiones; la conexión HTTP NO (no es segura entre hilos)."""
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise ConnectionError("No se pudo autenticar en Odoo. Revisa usuario/contraseña/DB.")
    return uid


_conexion_hilo = threading.local()


def conectar_odoo():
    """Cada hilo (cada sesión abierta) usa su propia conexión; compartirla causa errores 'Request-sent'."""
    uid = _autenticar_odoo()
    models = getattr(_conexion_hilo, "models", None)
    if models is None:
        models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
        _conexion_hilo.models = models
    return uid, models


def buscar_leer(models, uid, modelo, dominio, campos, limite=0, orden=""):
    kwargs = {"fields": campos, "limit": limite}
    if orden:
        kwargs["order"] = orden
    return models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        modelo, "search_read",
        [dominio], kwargs,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def campos_disponibles(modelo):
    """Nombres de campo reales que existen en este modelo (varía entre versiones de Odoo)."""
    uid, models = conectar_odoo()
    info = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, modelo, "fields_get", [], {"attributes": ["string"]})
    return set(info.keys())


def primer_campo_valido(modelo, candidatos):
    """Regresa el primer nombre de campo de la lista que sí existe en este modelo, o None."""
    disponibles = campos_disponibles(modelo)
    for c in candidatos:
        if c in disponibles:
            return c
    return None


# ============================================================
# EXTRACCIÓN DE DATOS (con caché corta para no saturar Odoo)
# ============================================================
@st.cache_data(ttl=30, show_spinner=False)
def get_ordenes_fabricacion():
    """Órdenes de fabricación (mrp.production) activas y recientes."""
    uid, models = conectar_odoo()

    campo_inicio_pl = primer_campo_valido("mrp.production", ["date_planned_start", "date_start"])
    campo_fin_pl = primer_campo_valido("mrp.production", ["date_planned_finished", "date_finished", "date_deadline"])
    campo_inicio_real = primer_campo_valido("mrp.production", ["date_start", "date_planned_start_wo"])
    campo_fin_real = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])

    campos_fijos = ["name", "product_id", "product_qty", "qty_producing", "state",
                     "origin", "user_id", "company_id", "bom_id", "workorder_ids"]
    campos_fecha = {c for c in [campo_inicio_pl, campo_fin_pl, campo_inicio_real, campo_fin_real] if c}
    disponibles = campos_disponibles("mrp.production")
    campos_reales = [c for c in campos_fijos if c in disponibles] + list(campos_fecha)

    dominio = [("state", "in", ["confirmed", "progress", "to_close", "planned"])]
    orden = f"{campo_inicio_pl} asc" if campo_inicio_pl else ""
    data = buscar_leer(models, uid, "mrp.production", dominio, campos_reales, orden=orden)
    df = pd.DataFrame(data)
    if df.empty:
        return df

    # Mapear cada campo real encontrado a los nombres canónicos que usa el resto del dashboard
    df["date_planned_start"] = df[campo_inicio_pl] if campo_inicio_pl in df.columns else pd.NA
    df["date_planned_finished"] = df[campo_fin_pl] if campo_fin_pl in df.columns else pd.NA
    df["date_start"] = df[campo_inicio_real] if campo_inicio_real in df.columns else pd.NA
    df["date_finished"] = df[campo_fin_real] if campo_fin_real in df.columns else pd.NA
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_ordenes_terminadas_hoy():
    uid, models = conectar_odoo()
    campo_fin = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])
    hoy = datetime.now().strftime("%Y-%m-%d 00:00:00")
    campos = ["name", "product_id", "product_qty", "qty_producing", "state"]
    if campo_fin:
        campos.append(campo_fin)
        dominio = [("state", "=", "done"), (campo_fin, ">=", hoy)]
    else:
        dominio = [("state", "=", "done"), ("write_date", ">=", hoy)]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["date_finished"] = df[campo_fin] if campo_fin and campo_fin in df.columns else pd.NA
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_workorders(orden_ids):
    """Órdenes de trabajo (mrp.workorder): quién, en qué centro, cuánto tiempo lleva."""
    if not orden_ids:
        return pd.DataFrame()
    uid, models = conectar_odoo()

    campo_inicio = primer_campo_valido("mrp.workorder", ["date_start", "date_planned_start"])
    campo_fin = primer_campo_valido("mrp.workorder", ["date_finished", "date_planned_finished"])

    campos_fijos = ["name", "production_id", "workcenter_id", "state", "duration_expected", "duration"]
    campos_fecha = {c for c in [campo_inicio, campo_fin] if c}
    disponibles = campos_disponibles("mrp.workorder")
    campos_reales = [c for c in campos_fijos if c in disponibles] + list(campos_fecha)

    dominio = [("production_id", "in", orden_ids)]
    data = buscar_leer(models, uid, "mrp.workorder", dominio, campos_reales)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["date_start"] = df[campo_inicio] if campo_inicio in df.columns else pd.NA
    df["date_finished"] = df[campo_fin] if campo_fin in df.columns else pd.NA
    return df


@st.cache_data(ttl=60, show_spinner=False)
def get_ordenes_completadas_periodo(fecha_inicio, fecha_fin):
    """Órdenes de fabricación cerradas (state=done) dentro de un rango de fechas."""
    uid, models = conectar_odoo()
    campo_fin = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])
    ini_str = fecha_inicio.strftime("%Y-%m-%d 00:00:00")
    fin_str = fecha_fin.strftime("%Y-%m-%d 23:59:59")
    campos = ["name", "product_id", "product_qty", "qty_producing", "state", "bom_id", "origin", "user_id"]
    if campo_fin:
        campos.append(campo_fin)
        dominio = [("state", "=", "done"), (campo_fin, ">=", ini_str), (campo_fin, "<=", fin_str)]
    else:
        dominio = [("state", "=", "done"), ("write_date", ">=", ini_str), ("write_date", "<=", fin_str)]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["date_finished"] = df[campo_fin] if campo_fin and campo_fin in df.columns else pd.to_datetime(df.get("write_date"))
    return df


@st.cache_data(ttl=60, show_spinner=False)
def get_ordenes_por_ids(ids):
    """Órdenes de fabricación por id (para reabrir un proyecto guardado, sin importar su fecha)."""
    if not ids:
        return pd.DataFrame()
    uid, models = conectar_odoo()
    campo_fin = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])
    campos = ["name", "product_id", "product_qty", "qty_producing", "state", "bom_id"]
    if campo_fin:
        campos.append(campo_fin)
    data = buscar_leer(models, uid, "mrp.production", [("id", "in", list(ids))], campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["date_finished"] = df[campo_fin] if campo_fin and campo_fin in df.columns else None
    return df


# Los proyectos (nombre + órdenes que los componen) se guardan en Odoo como un archivo
# adjunto JSON, así sobreviven a los reinicios de Streamlit y no se necesita ninguna cuenta extra.
NOMBRE_ARCHIVO_PROYECTOS = "marva_dashboard_proyectos.json"


def cargar_proyectos():
    uid, models = conectar_odoo()
    res = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.attachment", "search_read",
        [[("name", "=", NOMBRE_ARCHIVO_PROYECTOS)]], {"fields": ["id", "datas"], "limit": 1},
    )
    if not res or not res[0].get("datas"):
        return {}
    return json.loads(base64.b64decode(res[0]["datas"]).decode("utf-8"))


def guardar_proyectos(proyectos):
    uid, models = conectar_odoo()
    contenido = base64.b64encode(json.dumps(proyectos, ensure_ascii=False, indent=1).encode("utf-8")).decode("ascii")
    existentes = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.attachment", "search",
        [[("name", "=", NOMBRE_ARCHIVO_PROYECTOS)]], {"limit": 1},
    )
    if existentes:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "ir.attachment", "write", [existentes, {"datas": contenido}])
    else:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, "ir.attachment", "create",
            [{"name": NOMBRE_ARCHIVO_PROYECTOS, "datas": contenido, "mimetype": "application/json", "type": "binary"}],
        )


def mostrar_detalle_mano_obra(resultado_costos, clave):
    """Desplegable con lo que se leyó de cada empleado: minutos, costo por hora y costo."""
    with st.expander("👷 Mano de obra por empleado (minutos ÷ 60 × costo por hora)"):
        if resultado_costos is None or resultado_costos.empty:
            st.write("Sin datos de operaciones todavía.")
            return
        detalle = resultado_costos.attrs.get("empleados")
        nota = resultado_costos.attrs.get("nota", "")
        sin_tiempos = resultado_costos.attrs.get("operaciones_sin_tiempos", 0)
        if detalle is not None and not detalle.empty:
            st.dataframe(
                detalle, use_container_width=True, hide_index=True,
                column_config={
                    "Minutos": st.column_config.NumberColumn("Minutos", format="%.1f"),
                    "Costo por hora": st.column_config.NumberColumn("Costo por hora", format="$%.2f"),
                    "Costo": st.column_config.NumberColumn("Costo", format="$%.2f"),
                },
                key=clave,
            )
        if nota:
            st.info(nota)
        if sin_tiempos:
            st.caption(f"{sin_tiempos} operación(es) sin tiempo por empleado: se calcularon con el costo 'por empleado' del centro de trabajo.")


def _a_fecha(serie):
    """Odoo manda False en las fechas vacías; esto las convierte a NaT sin truenes."""
    return pd.to_datetime(serie.apply(lambda x: x if isinstance(x, str) else None), errors="coerce")


@st.cache_data(ttl=60, show_spinner=False)
def get_centros_trabajo():
    uid, models = conectar_odoo()
    disponibles = campos_disponibles("mrp.workcenter")
    campo_empleado = primer_campo_valido("mrp.workcenter", ["employee_costs_hour"])
    campos = [c for c in ["name", "costs_hour", "working_state"] if c in disponibles]
    if campo_empleado:
        campos.append(campo_empleado)
    data = buscar_leer(models, uid, "mrp.workcenter", [], campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    # Nombre estándar: costs_hour = costo por hora de MÁQUINA; employee_costs_hour = costo por hora del OPERADOR
    df["employee_costs_hour"] = df[campo_empleado] if campo_empleado else 0.0
    return df


@st.cache_data(ttl=60, show_spinner=False)
def get_alertas_calidad():
    """Alertas de calidad abiertas (quality.alert), si el módulo está instalado."""
    uid, models = conectar_odoo()
    try:
        campos = ["name", "product_id", "title", "stage_id", "user_id", "date_assign"]
        dominio = [("stage_id.name", "!=", "Cerrada")]
        data = buscar_leer(models, uid, "quality.alert", dominio, campos, limite=50)
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()  # módulo de calidad no instalado o sin permisos


@st.cache_data(ttl=120, show_spinner=False)
def get_fallas_calidad(dias=90):
    """Checklists de calidad (quality.check) que fallaron y bloquearon una operación."""
    uid, models = conectar_odoo()
    campo_estado = primer_campo_valido("quality.check", ["quality_state", "state"])
    campo_fecha = primer_campo_valido("quality.check", ["control_date", "date", "create_date"])
    if not campo_estado:
        return pd.DataFrame()
    campos = ["point_id", "production_id", "workorder_id", campo_estado]
    dominio = [(campo_estado, "=", "fail")]
    if campo_fecha:
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d 00:00:00")
        campos.append(campo_fecha)
        dominio.append((campo_fecha, ">=", desde))
    disponibles = campos_disponibles("quality.check")
    campos = [c for c in campos if c in disponibles]
    data = buscar_leer(models, uid, "quality.check", dominio, campos)
    return pd.DataFrame(data)


@st.cache_data(ttl=120, show_spinner=False)
def get_produccion_semanal(semanas=12):
    """Piezas producidas por semana, de órdenes ya cerradas — base para futura planeación por demanda."""
    uid, models = conectar_odoo()
    campo_fin = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])
    desde = (datetime.now() - timedelta(weeks=semanas)).strftime("%Y-%m-%d 00:00:00")
    campos = ["qty_producing", "state"]
    if campo_fin:
        campos.append(campo_fin)
        dominio = [("state", "=", "done"), (campo_fin, ">=", desde)]
    else:
        campos.append("write_date")
        dominio = [("state", "=", "done"), ("write_date", ">=", desde)]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    fecha_col = campo_fin if campo_fin and campo_fin in df.columns else "write_date"
    df["fecha"] = pd.to_datetime(df[fecha_col], errors="coerce")
    return df


@st.cache_data(ttl=120, show_spinner=False)
def get_eficiencia_historica(semanas=12):
    """Eficiencia (horas esperadas / horas reales) por centro de trabajo a lo largo del tiempo.
    Sirve como indicador indirecto de tiempo muerto, ya que no se registran motivos de paro."""
    uid, models = conectar_odoo()
    campo_fin = primer_campo_valido("mrp.workorder", ["date_finished", "date_planned_finished"])
    campos = ["workcenter_id", "duration_expected", "duration", "state"]
    dominio = [("state", "=", "done")]
    if campo_fin:
        desde = (datetime.now() - timedelta(weeks=semanas)).strftime("%Y-%m-%d 00:00:00")
        campos.append(campo_fin)
        dominio.append((campo_fin, ">=", desde))
    data = buscar_leer(models, uid, "mrp.workorder", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["fecha"] = pd.to_datetime(df[campo_fin], errors="coerce") if campo_fin and campo_fin in df.columns else pd.NaT
    return df


@st.cache_data(ttl=120, show_spinner=False)
def get_cumplimiento_entregas(dias=90):
    """Compara fecha planeada de fin vs. fecha real de fin en órdenes ya cerradas."""
    uid, models = conectar_odoo()
    campo_real = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])
    campo_plan = primer_campo_valido("mrp.production", ["date_planned_finished", "date_deadline"])
    if not campo_real or not campo_plan or campo_real == campo_plan:
        return pd.DataFrame()  # esta instalación de Odoo no distingue fecha planeada de fecha real
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d 00:00:00")
    campos = ["name", "product_id", campo_real, campo_plan]
    dominio = [("state", "=", "done"), (campo_real, ">=", desde)]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["fecha_real"] = pd.to_datetime(df[campo_real], errors="coerce")
    df["fecha_planeada"] = pd.to_datetime(df[campo_plan], errors="coerce")
    df["a_tiempo"] = df["fecha_real"] <= df["fecha_planeada"]
    df["dias_retraso"] = (df["fecha_real"] - df["fecha_planeada"]).dt.total_seconds() / 86400
    return df


@st.cache_data(ttl=120, show_spinner=False)
def get_tiempo_ciclo(dias=180):
    """Días entre que se crea una orden y se cierra, por producto — útil para cotizar tiempos futuros."""
    uid, models = conectar_odoo()
    campo_fin = primer_campo_valido("mrp.production", ["date_finished", "date_planned_finished"])
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d 00:00:00")
    campos = ["name", "product_id", "create_date"]
    if campo_fin:
        campos.append(campo_fin)
        dominio = [("state", "=", "done"), (campo_fin, ">=", desde)]
    else:
        campos.append("write_date")
        dominio = [("state", "=", "done"), ("write_date", ">=", desde)]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df
    fecha_col = campo_fin if campo_fin and campo_fin in df.columns else "write_date"
    df["fecha_inicio"] = pd.to_datetime(df["create_date"], errors="coerce")
    df["fecha_fin"] = pd.to_datetime(df[fecha_col], errors="coerce")
    df["dias_ciclo"] = (df["fecha_fin"] - df["fecha_inicio"]).dt.total_seconds() / 86400
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_consumo_materiales(orden_ids):
    """
    Consumo real de materia prima por orden (stock.move con
    raw_material_production_id). El costo se aproxima con el costo
    estándar del producto (standard_price); si Marva usa costeo FIFO/
    promedio con stock.valuation.layer, esto es una buena aproximación
    pero no el valor contable exacto.
    """
    if not orden_ids:
        return pd.DataFrame()
    uid, models = conectar_odoo()
    campos = [
        "product_id", "raw_material_production_id",
        "quantity_done", "product_uom_qty", "state",
    ]
    dominio = [
        ("raw_material_production_id", "in", orden_ids),
        ("state", "=", "done"),
    ]
    data = buscar_leer(models, uid, "stock.move", dominio, campos)
    df = pd.DataFrame(data)
    if df.empty:
        return df

    # Traer el costo estándar de cada producto consumido
    product_ids = df["product_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x).unique().tolist()
    precios = buscar_leer(models, uid, "product.product", [("id", "in", product_ids)], ["name", "standard_price"])
    df_precios = pd.DataFrame(precios).rename(columns={"id": "producto_id", "name": "Producto", "standard_price": "costo_unitario"})

    df["producto_id"] = df["product_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df["orden_id"] = df["raw_material_production_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df["orden"] = df["raw_material_production_id"].apply(nombre_relacion)
    df["cantidad"] = df["quantity_done"].where(df["quantity_done"] > 0, df["product_uom_qty"])

    df = df.merge(df_precios, on="producto_id", how="left")
    df["costo_real"] = df["cantidad"] * df["costo_unitario"].fillna(0)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def get_costo_planeado_materiales(df_ordenes):
    """Costo de materiales según receta (BOM), escalado a la cantidad a producir de cada orden.
    Regresa (df_costos_por_orden, df_diagnostico_por_componente)."""
    if df_ordenes.empty:
        return pd.DataFrame(), pd.DataFrame()
    uid, models = conectar_odoo()
    bom_ids = [x[0] if isinstance(x, (list, tuple)) else x for x in df_ordenes["bom_id"] if x]
    bom_ids = list(dict.fromkeys(bom_ids))  # únicos, conserva orden
    if not bom_ids:
        return pd.DataFrame(), pd.DataFrame()

    boms = buscar_leer(models, uid, "mrp.bom", [("id", "in", bom_ids)], ["id", "product_qty"])
    df_boms = pd.DataFrame(boms).rename(columns={"id": "bom_id", "product_qty": "bom_cantidad_base"})

    lineas = buscar_leer(models, uid, "mrp.bom.line", [("bom_id", "in", bom_ids)], ["bom_id", "product_id", "product_qty"])
    df_lineas = pd.DataFrame(lineas)
    if df_lineas.empty:
        return pd.DataFrame(), pd.DataFrame()
    df_lineas["bom_id"] = df_lineas["bom_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df_lineas["producto_id"] = df_lineas["product_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df_lineas["Producto"] = df_lineas["product_id"].apply(nombre_relacion)

    product_ids = df_lineas["producto_id"].unique().tolist()
    precios = buscar_leer(models, uid, "product.product", [("id", "in", product_ids)], ["standard_price"])
    df_precios = pd.DataFrame(precios).rename(columns={"id": "producto_id", "standard_price": "costo_unitario"})

    df_lineas = df_lineas.merge(df_precios, on="producto_id", how="left")
    df_lineas = df_lineas.merge(df_boms, on="bom_id", how="left")
    df_lineas["costo_linea"] = df_lineas["product_qty"] * df_lineas["costo_unitario"].fillna(0)
    diagnostico = df_lineas[["Producto", "product_qty", "costo_unitario", "costo_linea"]].rename(
        columns={"product_qty": "Cantidad en Receta", "costo_unitario": "Costo Unitario en Odoo", "costo_linea": "Costo de la Línea"}
    ).drop_duplicates(subset=["Producto"]).sort_values("Costo Unitario en Odoo")

    costo_bom = df_lineas.groupby("bom_id").agg(
        costo_por_lote=("costo_linea", "sum"),
        cantidad_base=("bom_cantidad_base", "first"),
    ).reset_index()
    costo_bom["costo_unitario_bom"] = costo_bom["costo_por_lote"] / costo_bom["cantidad_base"].replace(0, 1)

    ordenes = df_ordenes.copy()
    ordenes["bom_id"] = ordenes["bom_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    ordenes = ordenes.merge(costo_bom, on="bom_id", how="left")
    ordenes["costo_planeado"] = ordenes["costo_unitario_bom"].fillna(0) * ordenes["product_qty"]
    return ordenes[["id", "name", "costo_planeado"]], diagnostico


@st.cache_data(ttl=60, show_spinner=False)
def get_tiempos_empleados(workorder_ids):
    """Tiempo que cada empleado registró en cada operación (mrp.workcenter.productivity)
    junto con su 'Costo por hora' de la ficha del empleado (hr.employee).
    Regresa (df, nota). La nota explica por qué no hay datos, si es el caso."""
    columnas = ["workorder_id", "empleado", "emp_id", "minutos", "costo_hora"]
    if not workorder_ids:
        return pd.DataFrame(columns=columnas), "No hay operaciones."
    uid, models = conectar_odoo()
    try:
        disponibles = campos_disponibles("mrp.workcenter.productivity")
        if "employee_id" not in disponibles:
            return pd.DataFrame(columns=columnas), "Los registros de tiempo de Odoo no guardan el empleado (campo employee_id)."
        campos = [c for c in ["workorder_id", "employee_id", "duration"] if c in disponibles]
        data = buscar_leer(models, uid, "mrp.workcenter.productivity", [("workorder_id", "in", list(workorder_ids))], campos)
    except Exception as e:
        return pd.DataFrame(columns=columnas), f"No se pudieron leer los registros de tiempo: {str(e)[-150:]}"
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=columnas), "Las operaciones no tienen tiempo registrado todavía."

    df["workorder_id"] = df["workorder_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df["emp_id"] = df["employee_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else None)
    df["empleado"] = df["employee_id"].apply(lambda x: x[1] if isinstance(x, (list, tuple)) else "(sin empleado registrado)")
    df["minutos"] = pd.to_numeric(df["duration"], errors="coerce").fillna(0.0)

    nota = ""
    tarifas = {}
    emp_ids = [int(i) for i in df["emp_id"].dropna().unique()]
    try:
        campo_costo = primer_campo_valido("hr.employee", ["hourly_cost", "timesheet_cost"])
        if emp_ids and campo_costo:
            res = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, "hr.employee", "search_read",
                [[("id", "in", emp_ids)]], {"fields": [campo_costo], "context": {"active_test": False}},
            )
            tarifas = {r["id"]: float(r.get(campo_costo) or 0.0) for r in res}
        elif emp_ids:
            nota = "No encontré el campo 'Costo por hora' en la ficha del empleado."
    except Exception as e:
        nota = f"No se pudo leer el costo por hora de los empleados: {str(e)[-150:]}"
    df["costo_hora"] = df["emp_id"].map(tarifas).fillna(0.0)
    return df[columnas], nota


def get_costo_mano_obra(df_workorders, df_centros):
    """Costo real por orden, separado en operador y máquina.
    - Mano de obra: minutos que cada empleado registró ÷ 60 × su 'Costo por hora' (ficha del empleado).
      Si el empleado no tiene costo por hora, se usa el 'por empleado' del centro de trabajo.
      Si la operación no tiene tiempos por empleado, se usa el 'por empleado' del centro × horas de la operación.
    - Maquinaria: horas de la operación × costo por hora de la máquina (centro de trabajo).
    Regresa por orden: costo_mano_obra, costo_maquina, horas_trabajadas.
    En .attrs trae 'empleados' (detalle por empleado) y 'nota' (diagnóstico)."""
    if df_workorders.empty or df_centros.empty:
        return pd.DataFrame()
    wo = df_workorders.copy()
    wo["wo_id"] = wo["id"]
    wo["centro_id"] = wo["workcenter_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    wo["orden_id"] = wo["production_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    wo["orden"] = wo["production_id"].apply(nombre_relacion)

    centros = df_centros.rename(columns={
        "id": "centro_id", "costs_hour": "costo_hora_maquina", "employee_costs_hour": "costo_hora_empleado",
    })
    for col in ["costo_hora_maquina", "costo_hora_empleado"]:
        if col not in centros.columns:
            centros[col] = 0.0
    centros = centros[["centro_id", "costo_hora_maquina", "costo_hora_empleado"]]
    wo = wo.merge(centros, on="centro_id", how="left")
    horas = wo["duration"].fillna(0) / 60.0
    wo["costo_maquina"] = horas * wo["costo_hora_maquina"].fillna(0)
    wo["horas_trabajadas"] = horas

    # --- Mano de obra: tiempo por empleado × costo por hora del empleado ---
    try:
        logs, nota = get_tiempos_empleados([int(i) for i in wo["wo_id"].tolist()])
    except Exception as e:
        logs, nota = pd.DataFrame(columns=["workorder_id", "empleado", "emp_id", "minutos", "costo_hora"]), str(e)[-150:]
    tarifa_centro = wo.set_index("wo_id")["costo_hora_empleado"].fillna(0.0)
    detalle = pd.DataFrame()
    por_wo = pd.Series(dtype=float)
    if not logs.empty:
        logs = logs.copy()
        logs["tarifa_centro"] = logs["workorder_id"].map(tarifa_centro).fillna(0.0)
        logs["tarifa"] = logs["costo_hora"].where(logs["costo_hora"] > 0, logs["tarifa_centro"])
        logs["costo"] = logs["minutos"] / 60.0 * logs["tarifa"]
        por_wo = logs.groupby("workorder_id")["costo"].sum()
        detalle = logs.groupby("empleado").agg(
            Minutos=("minutos", "sum"), Costo_por_hora=("tarifa", "max"), Costo=("costo", "sum"),
        ).reset_index().rename(columns={"empleado": "Empleado", "Costo_por_hora": "Costo por hora"})
    wo["costo_mano_obra"] = wo["wo_id"].map(por_wo)
    sin_tiempos = wo["costo_mano_obra"].isna()
    wo.loc[sin_tiempos, "costo_mano_obra"] = horas[sin_tiempos] * wo.loc[sin_tiempos, "costo_hora_empleado"].fillna(0.0)

    resultado = wo.groupby(["orden_id", "orden"]).agg(
        costo_mano_obra=("costo_mano_obra", "sum"),
        costo_maquina=("costo_maquina", "sum"),
        horas_trabajadas=("horas_trabajadas", "sum"),
    ).reset_index()
    resultado.attrs["empleados"] = detalle
    resultado.attrs["nota"] = nota
    resultado.attrs["operaciones_sin_tiempos"] = int(sin_tiempos.sum())
    return resultado


@st.cache_data(ttl=60, show_spinner=False)
def get_ordenes_atrasadas(df_ordenes):
    if df_ordenes.empty:
        return df_ordenes
    ahora = datetime.now()
    df = df_ordenes.copy()
    df["date_planned_finished"] = pd.to_datetime(df["date_planned_finished"], errors="coerce")
    return df[(df["date_planned_finished"].notna()) & (df["date_planned_finished"] < ahora) & (df["state"] != "done")]


# ============================================================
# HELPERS DE FORMATO
# ============================================================
def nombre_relacion(campo):
    """Odoo regresa [id, 'Nombre'] en los campos many2one; esto extrae solo el nombre."""
    return campo[1] if isinstance(campo, (list, tuple)) and len(campo) > 1 else campo


def intentar(func, *args, etiqueta="esta sección", **kwargs):
    """Corre una función de extracción de datos; si Odoo truena por un campo
    que no existe en esta versión/instalación, muestra un aviso corto en vez
    de tumbar todo el dashboard."""
    try:
        return func(*args, **kwargs)
    except xmlrpc.client.Fault as e:
        mensaje = str(e.faultString).strip().split("\n")[-1] if e.faultString else str(e)
        st.warning(f"No se pudo cargar {etiqueta}: {mensaje[:200]}")
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"No se pudo cargar {etiqueta}: {e}")
        return pd.DataFrame()


def estilizar_grafica(fig):
    """Aplica la paleta de Marva (fondo oscuro + acentos ámbar) a una gráfica de Plotly."""
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=COLOR_FONDO_SEC,
        plot_bgcolor=COLOR_FONDO_SEC,
        font_color=COLOR_TEXTO,
        title_font_color=COLOR_TEXTO,
        legend_title_font_color=COLOR_TEXTO,
        margin=dict(t=50, l=10, r=10, b=10),
    )
    fig.update_xaxes(gridcolor=COLOR_BORDE)
    fig.update_yaxes(gridcolor=COLOR_BORDE)
    paleta = [COLOR_PRIMARIO, "#4A7FA6", "#7FA65C", "#C0553B", COLOR_TEXTO_SUAVE, "#E8C468"]
    fig.update_traces(marker_color=paleta[0]) if len(fig.data) == 1 and hasattr(fig.data[0], "marker") else None
    for i, trace in enumerate(fig.data):
        if hasattr(trace, "marker") and trace.marker.color is None:
            trace.marker.color = paleta[i % len(paleta)]
    return fig


# ============================================================
# UI
# ============================================================
col_refresh, col_status = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Actualizar ahora"):
        st.cache_data.clear()
        st.rerun()

try:
    uid, models = conectar_odoo()
    with col_status:
        st.success(f"Conectado a Odoo ({ODOO_DB}) como usuario id {uid}", icon="✅")
except Exception as e:
    st.error(f"No se pudo conectar a Odoo: {e}")
    st.info(
        "Revisa que ODOO_URL, ODOO_DB, ODOO_USER y ODOO_PASSWORD estén "
        "configurados correctamente en .streamlit/secrets.toml"
    )
    st.stop()

df_ordenes = intentar(get_ordenes_fabricacion, etiqueta="las órdenes de fabricación")
df_terminadas_hoy = intentar(get_ordenes_terminadas_hoy, etiqueta="las órdenes terminadas hoy")
df_atrasadas = get_ordenes_atrasadas(df_ordenes)

if not df_ordenes.empty:
    orden_ids = df_ordenes["id"].tolist()
    df_workorders = intentar(get_workorders, orden_ids, etiqueta="las órdenes de trabajo")
else:
    orden_ids = []
    df_workorders = pd.DataFrame()

df_centros = intentar(get_centros_trabajo, etiqueta="los centros de trabajo")
df_calidad = intentar(get_alertas_calidad, etiqueta="las alertas de calidad")

# ---------- Costos ----------
try:
    df_costo_planeado, df_diagnostico_bom = get_costo_planeado_materiales(df_ordenes)
except Exception as e:
    st.warning(f"No se pudo cargar el costo planeado (BOM): {e}")
    df_costo_planeado, df_diagnostico_bom = pd.DataFrame(), pd.DataFrame()
df_costo_mo = get_costo_mano_obra(df_workorders, df_centros)

costo_material_planeado_total = df_costo_planeado["costo_planeado"].sum() if not df_costo_planeado.empty else 0
costo_mano_obra_total = df_costo_mo["costo_mano_obra"].sum() if not df_costo_mo.empty else 0
costo_maquina_total = df_costo_mo["costo_maquina"].sum() if not df_costo_mo.empty else 0
costo_total_produccion = costo_material_planeado_total + costo_mano_obra_total + costo_maquina_total
componentes_sin_costo = int((df_diagnostico_bom["Costo Unitario en Odoo"].fillna(0) == 0).sum()) if not df_diagnostico_bom.empty else 0

# ---------- KPIs ----------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Órdenes en progreso", len(df_ordenes[df_ordenes["state"] == "progress"]) if not df_ordenes.empty else 0)
k2.metric("Órdenes planeadas/confirmadas", len(df_ordenes[df_ordenes["state"].isin(["confirmed", "planned"])]) if not df_ordenes.empty else 0)
k3.metric("Órdenes atrasadas", len(df_atrasadas))
k4.metric("Terminadas hoy", len(df_terminadas_hoy))
k5.metric("Alertas de calidad abiertas", len(df_calidad))

k6, k7, k8, k9, k10 = st.columns(5)
k6.metric("Costo materiales (BOM)", f"${costo_material_planeado_total:,.0f}")
k7.metric("Costo mano de obra (real)", f"${costo_mano_obra_total:,.0f}")
k8.metric("Costo maquinaria (real)", f"${costo_maquina_total:,.0f}")
k9.metric("Costo total de producción", f"${costo_total_produccion:,.0f}")
k10.metric("Componentes sin costo", f"{componentes_sin_costo} de {len(df_diagnostico_bom)}" if not df_diagnostico_bom.empty else "0 de 0")

st.divider()

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab_proyectos, tab8 = st.tabs([
    "📋 Órdenes en piso", "⚙️ Centros de trabajo", "⏱️ Horas y avance",
    "💰 Costos", "✅ Calidad", "📦 Terminadas hoy", "📊 Acumulado por periodo",
    "🏗️ Proyectos", "📈 Análisis",
])

# ---------- TAB 1: Órdenes en piso ----------
with tab1:
    st.subheader("Órdenes de fabricación activas")
    if df_ordenes.empty:
        st.info("No hay órdenes activas en este momento.")
    else:
        tabla = df_ordenes.copy()
        tabla["Producto"] = tabla["product_id"].apply(nombre_relacion)
        tabla["Responsable"] = tabla["user_id"].apply(nombre_relacion)
        tabla["% Avance"] = (tabla["qty_producing"] / tabla["product_qty"].replace(0, 1) * 100).round(1)
        tabla_mostrar = tabla[[
            "name", "Producto", "product_qty", "qty_producing", "% Avance",
            "state", "date_planned_start", "date_planned_finished", "Responsable",
        ]].rename(columns={
            "name": "Orden", "product_qty": "Cant. Planeada",
            "qty_producing": "Cant. Producida", "state": "Estado",
            "date_planned_start": "Inicio Planeado", "date_planned_finished": "Fin Planeado",
        })
        st.dataframe(tabla_mostrar, use_container_width=True, hide_index=True)

        if not df_atrasadas.empty:
            st.warning(f"⚠️ {len(df_atrasadas)} orden(es) atrasada(s) respecto a su fecha planeada de fin")
            st.dataframe(df_atrasadas[["name", "date_planned_finished", "state"]], use_container_width=True, hide_index=True)

# ---------- TAB 2: Centros de trabajo ----------
with tab2:
    st.subheader("Carga por centro de trabajo")
    if df_workorders.empty:
        st.info("No hay órdenes de trabajo activas.")
    else:
        wo = df_workorders.copy()
        wo["Centro"] = wo["workcenter_id"].apply(nombre_relacion)
        carga = wo.groupby(["Centro", "state"]).size().reset_index(name="Cantidad")
        fig = px.bar(carga, x="Centro", y="Cantidad", color="state", barmode="stack",
                     title="Órdenes de trabajo por centro y estado")
        st.plotly_chart(estilizar_grafica(fig), use_container_width=True, key="grafica_carga_centro")

        st.markdown("**Carga futura: horas comprometidas por centro de trabajo**")
        st.caption("Horas planeadas de las operaciones que aún no terminan (pendientes + en progreso) — para anticipar cuellos de botella.")
        wo_pendiente = wo[wo["state"] != "done"].copy()
        if wo_pendiente.empty:
            st.info("No hay horas pendientes por asignar en este momento.")
        else:
            carga_horas = wo_pendiente.groupby(["Centro", "state"]).agg(
                horas=("duration_expected", lambda s: s.sum() / 60.0)
            ).reset_index()
            fig_carga = px.bar(carga_horas, x="Centro", y="horas", color="state", barmode="stack",
                                title="Horas comprometidas por centro de trabajo")
            st.plotly_chart(estilizar_grafica(fig_carga), use_container_width=True, key="grafica_horas_comprometidas")

        if not df_centros.empty:
            st.dataframe(
                df_centros.rename(columns={"name": "Centro", "costs_hour": "Costo/Hora Máquina", "employee_costs_hour": "Costo/Hora Operador", "working_state": "Estado Actual"}),
                use_container_width=True, hide_index=True,
            )

# ---------- TAB 3: Horas y avance ----------
with tab3:
    st.subheader("Horas planeadas vs. reales")
    if df_workorders.empty:
        st.info("No hay datos de tiempos todavía.")
    else:
        wo = df_workorders.copy()
        wo["Centro"] = wo["workcenter_id"].apply(nombre_relacion)
        wo["Orden"] = wo["production_id"].apply(nombre_relacion)
        comparativa = wo[["Orden", "Centro", "name", "duration_expected", "duration", "state"]].rename(columns={
            "name": "Operación", "duration_expected": "Min. Esperados", "duration": "Min. Reales",
        })
        comparativa["Eficiencia %"] = (
            comparativa["Min. Esperados"] / comparativa["Min. Reales"].replace(0, float("nan")) * 100
        ).round(1)
        st.dataframe(comparativa, use_container_width=True, hide_index=True)

        total_esperado = comparativa["Min. Esperados"].sum()
        total_real = comparativa["Min. Reales"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total minutos esperados", f"{total_esperado:,.0f}")
        c2.metric("Total minutos reales", f"{total_real:,.0f}")
        if total_real > 0:
            c3.metric("Eficiencia global", f"{(total_esperado/total_real*100):.1f}%")

# ---------- TAB 4: Costos ----------
with tab4:
    st.subheader("Costo de producción por orden")
    st.caption(
        "Materiales = costo estimado según la receta (BOM) de cada producto, ya que el "
        "inventario real se controla en otro sistema. Mano de obra = tiempo que cada empleado registró × su "
        "'Costo por hora' (ficha del empleado); Maquinaria = horas reales × costo-hora de la máquina (centro de trabajo)."
    )

    with st.expander("🔍 Diagnóstico: costo unitario que el dashboard está leyendo de cada componente"):
        if df_diagnostico_bom.empty:
            st.write("No se encontró ningún componente de receta (BOM) en las órdenes activas.")
        else:
            st.caption("Si un componente aparece en $0 aquí pero sí tiene costo en su ficha de producto en Odoo, dime el nombre exacto del producto y seguimos investigando ese caso puntual.")
            st.dataframe(df_diagnostico_bom, use_container_width=True, hide_index=True)

    mostrar_detalle_mano_obra(df_costo_mo, "tabla_mano_obra_costos")

    if df_costo_planeado.empty and df_costo_mo.empty:
        st.info("Aún no hay órdenes con receta (BOM) o tiempos registrados.")
    else:
        resumen = df_costo_planeado.rename(columns={"id": "orden_id", "name": "orden"}) if not df_costo_planeado.empty else pd.DataFrame(columns=["orden_id", "orden", "costo_planeado"])
        if not df_costo_mo.empty:
            resumen = resumen.merge(df_costo_mo, on=["orden_id", "orden"], how="outer")
        resumen = resumen.fillna(0)
        for col in ["costo_planeado", "costo_mano_obra", "costo_maquina"]:
            if col not in resumen.columns:
                resumen[col] = 0.0
        resumen["costo_total"] = resumen["costo_planeado"] + resumen["costo_mano_obra"] + resumen["costo_maquina"]

        if not df_ordenes.empty:
            piezas = df_ordenes[["id", "qty_producing"]].rename(columns={"id": "orden_id"})
            resumen = resumen.merge(piezas, on="orden_id", how="left")
            resumen["qty_producing"] = resumen["qty_producing"].fillna(0)
            resumen["costo_por_pieza"] = resumen.apply(
                lambda r: r["costo_total"] / r["qty_producing"] if r["qty_producing"] > 0 else None, axis=1
            )

        tabla_costos = resumen.rename(columns={
            "orden": "Orden", "costo_planeado": "Materiales (BOM)",
            "costo_mano_obra": "Mano de Obra", "costo_maquina": "Maquinaria",
            "horas_trabajadas": "Horas Trabajadas", "costo_total": "Costo Total",
            "qty_producing": "Piezas Producidas", "costo_por_pieza": "Costo por Pieza",
        }).drop(columns=["orden_id"], errors="ignore")
        st.dataframe(tabla_costos, use_container_width=True, hide_index=True)

        st.markdown("**Desglose de costo de operación por centro de trabajo (operador + máquina)**")
        if not df_workorders.empty and not df_centros.empty:
            wo = df_workorders.copy()
            wo["Centro"] = wo["workcenter_id"].apply(nombre_relacion)
            centros_costo = df_centros.rename(columns={"id": "centro_id", "costs_hour": "costo_hora_maquina", "employee_costs_hour": "costo_hora_empleado"})
            for col in ["costo_hora_maquina", "costo_hora_empleado"]:
                if col not in centros_costo.columns:
                    centros_costo[col] = 0.0
            wo["centro_id"] = wo["workcenter_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
            wo = wo.merge(centros_costo[["centro_id", "costo_hora_maquina", "costo_hora_empleado"]], on="centro_id", how="left")
            wo["costo"] = (wo["duration"] / 60.0) * (wo["costo_hora_maquina"].fillna(0) + wo["costo_hora_empleado"].fillna(0))
            por_centro = wo.groupby("Centro").agg(
                horas_reales=("duration", lambda s: s.sum() / 60.0), costo=("costo", "sum")
            ).reset_index()
            fig_centro = px.bar(por_centro, x="Centro", y="costo", title="Costo de mano de obra por centro de trabajo")
            st.plotly_chart(estilizar_grafica(fig_centro), use_container_width=True, key="grafica_costo_mano_obra_centro")
        else:
            st.info("Aún no hay horas registradas en órdenes de trabajo.")

# ---------- TAB 5: Calidad ----------
with tab5:
    st.subheader("Alertas de calidad abiertas")
    if df_calidad.empty:
        st.info("No hay alertas abiertas, o el módulo de Calidad no está instalado / accesible.")
    else:
        cal = df_calidad.copy()
        cal["Producto"] = cal["product_id"].apply(nombre_relacion)
        cal["Etapa"] = cal["stage_id"].apply(nombre_relacion)
        cal["Responsable"] = cal["user_id"].apply(nombre_relacion)
        st.dataframe(
            cal[["name", "title", "Producto", "Etapa", "Responsable", "date_assign"]].rename(
                columns={"name": "Referencia", "title": "Título", "date_assign": "Fecha"}
            ),
            use_container_width=True, hide_index=True,
        )

# ---------- TAB 6: Terminadas hoy ----------
with tab6:
    st.subheader("Órdenes terminadas hoy")
    if df_terminadas_hoy.empty:
        st.info("Aún no se ha terminado ninguna orden hoy.")
    else:
        term = df_terminadas_hoy.copy()
        term["Producto"] = term["product_id"].apply(nombre_relacion)
        st.dataframe(
            term[["name", "Producto", "product_qty", "qty_producing", "date_finished"]].rename(
                columns={"name": "Orden", "product_qty": "Planeado", "qty_producing": "Producido", "date_finished": "Hora Fin"}
            ),
            use_container_width=True, hide_index=True,
        )

# ---------- TAB 7: Acumulado por periodo ----------
with tab7:
    st.subheader("Resumen acumulado")
    st.caption("Suma órdenes ya **cerradas** (Hecho) dentro del rango de fechas que elijas — para reportería, no para piso en vivo.")

    hoy = datetime.now().date()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    if "rango_acumulado" not in st.session_state:
        st.session_state.rango_acumulado = (inicio_semana, hoy)
    if col_r1.button("Semana actual", use_container_width=True):
        st.session_state.rango_acumulado = (inicio_semana, hoy)
    if col_r2.button("Últimos 7 días", use_container_width=True):
        st.session_state.rango_acumulado = (hoy - timedelta(days=7), hoy)
    if col_r3.button("Mes actual", use_container_width=True):
        st.session_state.rango_acumulado = (inicio_mes, hoy)
    if col_r4.button("Últimos 30 días", use_container_width=True):
        st.session_state.rango_acumulado = (hoy - timedelta(days=30), hoy)

    rango = st.date_input(
        "O elige un rango personalizado",
        value=st.session_state.rango_acumulado,
        max_value=hoy,
    )
    if isinstance(rango, tuple) and len(rango) == 2:
        fecha_inicio, fecha_fin = rango
    else:
        fecha_inicio, fecha_fin = st.session_state.rango_acumulado

    df_periodo = intentar(get_ordenes_completadas_periodo, fecha_inicio, fecha_fin, etiqueta="el acumulado del periodo")

    if df_periodo.empty:
        st.info(f"No hay órdenes cerradas entre {fecha_inicio} y {fecha_fin}.")
    else:
        ids_periodo = df_periodo["id"].tolist()
        wo_periodo = intentar(get_workorders, ids_periodo, etiqueta="las horas del periodo")
        try:
            costo_mat_periodo, _ = get_costo_planeado_materiales(df_periodo)
        except Exception as e:
            st.warning(f"No se pudo cargar el costo de materiales del periodo: {e}")
            costo_mat_periodo = pd.DataFrame()
        costo_mo_periodo = get_costo_mano_obra(wo_periodo, df_centros)

        total_mat = costo_mat_periodo["costo_planeado"].sum() if not costo_mat_periodo.empty else 0
        total_mo = costo_mo_periodo["costo_mano_obra"].sum() if not costo_mo_periodo.empty else 0
        total_maq = costo_mo_periodo["costo_maquina"].sum() if not costo_mo_periodo.empty else 0
        total_costo = total_mat + total_mo + total_maq
        total_piezas = df_periodo["qty_producing"].sum()

        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Órdenes cerradas", len(df_periodo))
        p2.metric("Piezas producidas", f"{total_piezas:,.0f}")
        p3.metric("Costo materiales (BOM)", f"${total_mat:,.0f}")
        p4.metric("Costo mano de obra", f"${total_mo:,.0f}")
        p5.metric("Costo maquinaria", f"${total_maq:,.0f}")

        st.markdown(f"**Costo total del periodo: ${total_costo:,.0f}**")

        tabla_periodo = df_periodo.copy()
        tabla_periodo["Producto"] = tabla_periodo["product_id"].apply(nombre_relacion)
        tabla_periodo["Fecha Fin"] = pd.to_datetime(tabla_periodo["date_finished"], errors="coerce")
        st.dataframe(
            tabla_periodo[["name", "Producto", "product_qty", "qty_producing", "Fecha Fin"]].rename(
                columns={"name": "Orden", "product_qty": "Planeado", "qty_producing": "Producido"}
            ).sort_values("Fecha Fin"),
            use_container_width=True, hide_index=True,
        )

        # Gráfica de piezas producidas por día dentro del rango
        por_dia = tabla_periodo.copy()
        por_dia["Día"] = por_dia["Fecha Fin"].dt.date
        resumen_dia = por_dia.groupby("Día").agg(piezas=("qty_producing", "sum"), ordenes=("name", "count")).reset_index()
        fig_dia = px.bar(resumen_dia, x="Día", y="piezas", title="Piezas producidas por día")
        st.plotly_chart(estilizar_grafica(fig_dia), use_container_width=True, key="grafica_piezas_por_dia_periodo")

# ---------- TAB Proyectos ----------
with tab_proyectos:
    st.subheader("Proyectos")
    st.caption(
        "Agrupa órdenes de fabricación **terminadas** en un proyecto (ej. una cimentación elevada) y ve el "
        "costo y el tiempo reales de cada línea y del total. Todo sale de las órdenes en Odoo."
    )

    hoy_p = datetime.now().date()

    # --- Cargar proyectos guardados (una vez por sesión) ---
    error_lectura = ""
    if "proyectos" not in st.session_state:
        try:
            st.session_state["proyectos"] = cargar_proyectos()
        except Exception as e:
            error_lectura = str(e)
    proyectos = st.session_state.get("proyectos")
    if proyectos is None:
        # No se pudo leer: no se muestra nada editable para no sobrescribir los proyectos ya guardados.
        st.warning(f"No pude leer los proyectos guardados en Odoo: {error_lectura[:200]}")
        st.button("🔄 Reintentar", key="btn_reintentar_proyectos")
        proyectos = None

    # --- Crear proyecto nuevo ---
    col_n1, col_n2 = st.columns([4, 1])
    nuevo_nombre = col_n1.text_input("Nuevo proyecto", placeholder="Ej. 1-2-6 Cimentación elevada de silo", key="nuevo_proyecto_nombre", disabled=proyectos is None)
    col_n2.write("")
    if col_n2.button("➕ Crear", key="btn_crear_proyecto", use_container_width=True, disabled=proyectos is None):
        nombre_limpio = nuevo_nombre.strip()
        if not nombre_limpio:
            st.warning("Escribe un nombre para el proyecto.")
        elif nombre_limpio in proyectos:
            st.warning("Ya existe un proyecto con ese nombre.")
        else:
            proyectos[nombre_limpio] = {"ordenes": [], "creado": str(hoy_p)}
            try:
                guardar_proyectos(proyectos)
            except Exception as e:
                st.error(f"El proyecto quedó solo en esta sesión; no se pudo guardar en Odoo: {str(e)[:200]}")
            st.session_state["proyecto_activo"] = nombre_limpio

    if proyectos is None:
        pass
    elif not proyectos:
        st.info("Todavía no hay proyectos. Crea el primero arriba.")
    else:
        activo = st.selectbox("Proyecto", sorted(proyectos.keys()), key="proyecto_activo")
        guardadas = [int(i) for i in proyectos[activo].get("ordenes", [])]

        dias_busqueda = st.selectbox(
            "Buscar órdenes terminadas de los últimos…", [30, 90, 180, 365, 730], index=3,
            format_func=lambda d: f"{d} días", key="proyecto_dias_busqueda",
        )
        df_pool = intentar(get_ordenes_completadas_periodo, hoy_p - timedelta(days=dias_busqueda), hoy_p, etiqueta="las órdenes terminadas")
        df_guardadas = intentar(get_ordenes_por_ids, guardadas, etiqueta="las órdenes del proyecto") if guardadas else pd.DataFrame()
        marcos = [d for d in [df_pool, df_guardadas] if not d.empty]
        base_ordenes = pd.concat(marcos, ignore_index=True).drop_duplicates(subset="id") if marcos else pd.DataFrame()

        if base_ordenes.empty:
            st.info("No hay órdenes terminadas en ese periodo para agregar al proyecto.")
        else:
            etiquetas = {}
            for _, r in base_ordenes.iterrows():
                fecha_txt = r["date_finished"][:10] if isinstance(r.get("date_finished"), str) else ""
                etiquetas[int(r["id"])] = f"{r['name']} · {nombre_relacion(r['product_id'])} · {r['product_qty']:g} pz · {fecha_txt}"

            clave_sel = f"sel_ordenes_{activo}"
            if clave_sel not in st.session_state:
                st.session_state[clave_sel] = [i for i in guardadas if i in etiquetas]
            seleccion = st.multiselect(
                "Órdenes de fabricación que componen el proyecto",
                sorted(etiquetas.keys(), key=lambda i: etiquetas[i]),
                key=clave_sel, format_func=lambda i: etiquetas.get(i, str(i)),
            )

            if not seleccion:
                st.info("Selecciona las órdenes que componen este proyecto; los totales se calculan al ir agregando.")
            else:
                df_sel = base_ordenes[base_ordenes["id"].isin(seleccion)].copy()
                wo_sel = intentar(get_workorders, list(seleccion), etiqueta="las operaciones del proyecto")
                try:
                    costo_mat_sel, _ = get_costo_planeado_materiales(df_sel)
                except Exception as e:
                    st.warning(f"No se pudo calcular el costo de materiales: {e}")
                    costo_mat_sel = pd.DataFrame()
                costo_op_sel = get_costo_mano_obra(wo_sel, df_centros)

                t = df_sel[["id", "name", "product_id", "product_qty", "qty_producing"]].copy()
                t["Producto"] = t["product_id"].apply(nombre_relacion)
                t["Piezas"] = t["qty_producing"].where(t["qty_producing"] > 0, t["product_qty"])
                if not costo_mat_sel.empty:
                    t = t.merge(costo_mat_sel[["id", "costo_planeado"]], on="id", how="left")
                else:
                    t["costo_planeado"] = 0.0
                if not costo_op_sel.empty:
                    t = t.merge(
                        costo_op_sel.rename(columns={"orden_id": "id"})[["id", "costo_mano_obra", "costo_maquina", "horas_trabajadas"]],
                        on="id", how="left",
                    )
                else:
                    t["costo_mano_obra"] = 0.0
                    t["costo_maquina"] = 0.0
                    t["horas_trabajadas"] = 0.0
                if not wo_sel.empty:
                    w = wo_sel.copy()
                    w["id"] = w["production_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
                    w["ini"] = _a_fecha(w["date_start"])
                    w["fin"] = _a_fecha(w["date_finished"])
                    fechas = w.groupby("id").agg(Inicio=("ini", "min"), Fin=("fin", "max")).reset_index()
                    t = t.merge(fechas, on="id", how="left")
                else:
                    t["Inicio"] = pd.NaT
                    t["Fin"] = pd.NaT
                for col in ["costo_planeado", "costo_mano_obra", "costo_maquina", "horas_trabajadas"]:
                    t[col] = t[col].fillna(0.0)
                t["costo_total"] = t["costo_planeado"] + t["costo_mano_obra"] + t["costo_maquina"]
                t["costo_pieza"] = t.apply(lambda r: r["costo_total"] / r["Piezas"] if r["Piezas"] > 0 else None, axis=1)
                t = t.sort_values("Inicio", na_position="last")

                # --- Totales del proyecto ---
                tot_mo = t["costo_mano_obra"].sum()
                tot_maq = t["costo_maquina"].sum()
                tot_mat = t["costo_planeado"].sum()
                tot_costo = tot_mo + tot_maq + tot_mat
                tot_horas = t["horas_trabajadas"].sum()

                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Mano de obra", f"${tot_mo:,.0f}")
                m2.metric("Maquinaria", f"${tot_maq:,.0f}")
                m3.metric("Materiales", f"${tot_mat:,.0f}")
                m4.metric("Costo total del proyecto", f"${tot_costo:,.0f}")
                m5.metric("Horas trabajadas", f"{tot_horas:,.1f} h")

                # --- Tabla por línea + fila de totales ---
                tabla_p = pd.DataFrame({
                    "Orden": t["name"], "Producto": t["Producto"], "Piezas": t["Piezas"],
                    "Mano de obra": t["costo_mano_obra"], "Maquinaria": t["costo_maquina"],
                    "Materiales": t["costo_planeado"], "Costo total": t["costo_total"],
                    "Costo por pieza": t["costo_pieza"], "Horas trabajadas": t["horas_trabajadas"],
                    "Inicio": t["Inicio"].dt.strftime("%Y-%m-%d").fillna(""),
                    "Fin": t["Fin"].dt.strftime("%Y-%m-%d").fillna(""),
                })
                fila_total = pd.DataFrame([{
                    "Orden": "TOTAL DEL PROYECTO", "Producto": "", "Piezas": None,
                    "Mano de obra": tot_mo, "Maquinaria": tot_maq, "Materiales": tot_mat,
                    "Costo total": tot_costo, "Costo por pieza": None, "Horas trabajadas": tot_horas,
                    "Inicio": t["Inicio"].min().strftime("%Y-%m-%d") if t["Inicio"].notna().any() else "",
                    "Fin": t["Fin"].max().strftime("%Y-%m-%d") if t["Fin"].notna().any() else "",
                }])
                tabla_final = pd.concat([tabla_p, fila_total], ignore_index=True)
                columnas_dinero = ["Mano de obra", "Maquinaria", "Materiales", "Costo total", "Costo por pieza"]
                config_cols = {c: st.column_config.NumberColumn(c, format="$%.2f") for c in columnas_dinero}
                config_cols["Piezas"] = st.column_config.NumberColumn("Piezas", format="%.0f")
                config_cols["Horas trabajadas"] = st.column_config.NumberColumn("Horas trabajadas", format="%.1f")
                st.dataframe(tabla_final, use_container_width=True, hide_index=True, column_config=config_cols)

                st.markdown(
                    f"**Resumen:** mano de obra ${tot_mo:,.0f} · maquinaria ${tot_maq:,.0f} · materiales ${tot_mat:,.0f} "
                    f"→ **total ${tot_costo:,.0f}** en **{tot_horas:,.1f} horas trabajadas**."
                )
                st.caption("El costo por pieza solo tiene sentido dentro de cada línea (mismo producto); por eso la fila de totales no lo promedia.")

                # --- Gráfica de costo por línea ---
                largo = tabla_p[["Orden", "Mano de obra", "Maquinaria", "Materiales"]].melt(
                    id_vars="Orden", var_name="Concepto", value_name="Costo")
                fig_proy = px.bar(
                    largo, x="Orden", y="Costo", color="Concepto", barmode="stack",
                    title="Costo por línea del proyecto",
                    color_discrete_map={"Mano de obra": COLOR_PRIMARIO, "Maquinaria": "#4A7FA6", "Materiales": "#7FA65C"},
                )
                st.plotly_chart(estilizar_grafica(fig_proy), use_container_width=True, key="grafica_proyecto_costos")

                # --- Avisos de datos incompletos ---
                mostrar_detalle_mano_obra(costo_op_sel, "tabla_mano_obra_proyecto")
                n_sin_tiempos = costo_op_sel.attrs.get("operaciones_sin_tiempos", 0) if not costo_op_sel.empty else 0
                if n_sin_tiempos:
                    st.warning(
                        f"{n_sin_tiempos} operación(es) no tienen tiempo registrado por empleado; su mano de obra se calculó "
                        "con el costo 'por empleado' del centro de trabajo (si ahí es $0, queda en $0). Para que cuente el "
                        "costo por hora del empleado, el operador debe iniciar y terminar la operación en Taller con su usuario."
                    )
                if tot_mo <= 0 and tot_horas > 0:
                    nota_mo = costo_op_sel.attrs.get("nota", "") if not costo_op_sel.empty else ""
                    st.warning(
                        "La mano de obra sale en $0: ningún empleado con tiempo registrado tiene 'Costo por hora' "
                        "(ficha del empleado → Ajustes de RR. HH.)." + (f" {nota_mo}" if nota_mo else "")
                    )
                sin_mat = t.loc[t["costo_planeado"] <= 0, "name"].tolist()
                if sin_mat:
                    st.warning("Materiales en $0 en: " + ", ".join(sin_mat) + " (sin receta BOM o con componentes sin costo en Odoo).")
                sin_horas = t.loc[t["horas_trabajadas"] <= 0, "name"].tolist()
                if sin_horas:
                    st.warning("Sin horas registradas en: " + ", ".join(sin_horas) + " (no se registró tiempo en sus operaciones).")

            # --- Acciones ---
            acc1, acc2, acc3 = st.columns(3)
            if acc1.button("💾 Guardar proyecto", key="btn_guardar_proyecto", use_container_width=True):
                proyectos[activo]["ordenes"] = [int(i) for i in seleccion]
                proyectos[activo]["actualizado"] = str(hoy_p)
                try:
                    guardar_proyectos(proyectos)
                    st.success("Proyecto guardado en Odoo.")
                except Exception as e:
                    st.error(f"No se pudo guardar en Odoo: {str(e)[:200]}")
            if seleccion:
                acc2.download_button(
                    "⬇️ Descargar tabla (CSV)", data=tabla_final.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"proyecto_{activo}.csv".replace(" ", "_"), mime="text/csv",
                    key="btn_descargar_proyecto", use_container_width=True,
                )

        with st.expander("🗑️ Eliminar este proyecto"):
            confirmar = st.checkbox(f"Sí, eliminar «{activo}» (las órdenes en Odoo no se tocan)", key="confirmar_eliminar_proyecto")
            if st.button("Eliminar proyecto", key="btn_eliminar_proyecto", disabled=not confirmar):
                proyectos.pop(activo, None)
                try:
                    guardar_proyectos(proyectos)
                except Exception as e:
                    st.error(f"No se pudo actualizar en Odoo: {str(e)[:200]}")
                st.session_state.pop("proyecto_activo", None)
                st.session_state.pop(f"sel_ordenes_{activo}", None)
                st.session_state.pop("confirmar_eliminar_proyecto", None)
                st.rerun()

# ---------- TAB 8: Análisis ----------
with tab8:
    st.subheader("Cumplimiento de fecha de entrega")
    st.caption("% de órdenes cerradas en la fecha planeada o antes, últimos 90 días.")
    df_cumplimiento = intentar(get_cumplimiento_entregas, etiqueta="el cumplimiento de entregas")
    if df_cumplimiento.empty:
        st.info(
            "Aún no hay suficientes órdenes cerradas con fecha planeada de entrega para calcular esto "
            "(o esta versión de Odoo no distingue fecha planeada de fecha real)."
        )
    else:
        pct_a_tiempo = df_cumplimiento["a_tiempo"].mean() * 100
        c1, c2, c3 = st.columns(3)
        c1.metric("Entregado a tiempo", f"{pct_a_tiempo:.0f}%")
        c2.metric("Órdenes analizadas", len(df_cumplimiento))
        promedio_retraso = df_cumplimiento.loc[~df_cumplimiento["a_tiempo"], "dias_retraso"].mean()
        c3.metric("Retraso promedio (cuando se atrasa)", f"{promedio_retraso:.1f} días" if pd.notna(promedio_retraso) else "N/A")

        df_cumplimiento["Semana"] = df_cumplimiento["fecha_real"].dt.to_period("W").apply(lambda p: p.start_time.date())
        semanal_cumpl = df_cumplimiento.groupby("Semana").agg(pct_a_tiempo=("a_tiempo", "mean")).reset_index()
        semanal_cumpl["pct_a_tiempo"] = (semanal_cumpl["pct_a_tiempo"] * 100).round(1)
        fig_cumpl = px.line(semanal_cumpl, x="Semana", y="pct_a_tiempo", markers=True,
                             title="% de entregas a tiempo por semana")
        fig_cumpl.update_yaxes(range=[0, 105])
        st.plotly_chart(estilizar_grafica(fig_cumpl), use_container_width=True, key="grafica_cumplimiento_entregas")

        atrasadas_hist = df_cumplimiento[~df_cumplimiento["a_tiempo"]].sort_values("dias_retraso", ascending=False)
        if not atrasadas_hist.empty:
            st.markdown("**Órdenes con mayor retraso**")
            atrasadas_hist["Producto"] = atrasadas_hist["product_id"].apply(nombre_relacion)
            st.dataframe(
                atrasadas_hist[["name", "Producto", "dias_retraso"]].rename(
                    columns={"name": "Orden", "dias_retraso": "Días de Retraso"}
                ).round(1).head(10),
                use_container_width=True, hide_index=True,
            )

    st.divider()
    st.subheader("Tiempo de ciclo por producto")
    st.caption("Días desde que se crea la orden hasta que se cierra — útil para cotizar tiempos de entrega en proyectos futuros.")
    df_ciclo = intentar(get_tiempo_ciclo, etiqueta="el tiempo de ciclo")
    if df_ciclo.empty:
        st.info("Aún no hay suficiente historial de órdenes cerradas para calcular tiempos de ciclo.")
    else:
        df_ciclo["Producto"] = df_ciclo["product_id"].apply(nombre_relacion)
        ciclo_producto = df_ciclo.groupby("Producto").agg(
            dias_promedio=("dias_ciclo", "mean"), ordenes=("name", "count")
        ).reset_index().sort_values("dias_promedio", ascending=False).head(15)
        fig_ciclo = px.bar(ciclo_producto, x="Producto", y="dias_promedio",
                            title="Días de ciclo promedio por producto (top 15)")
        st.plotly_chart(estilizar_grafica(fig_ciclo), use_container_width=True, key="grafica_tiempo_ciclo")
        st.metric("Tiempo de ciclo promedio general", f"{df_ciclo['dias_ciclo'].mean():.1f} días")

    st.divider()
    st.subheader("Pareto de fallas de calidad")
    st.caption(
        "Puntos de control de tus checklists que más veces han bloqueado una operación "
        "en los últimos 90 días."
    )
    df_fallas = intentar(get_fallas_calidad, etiqueta="las fallas de calidad")
    if df_fallas.empty:
        st.info("Aún no hay fallas de calidad registradas (o los checklists son muy nuevos).")
    else:
        df_fallas["Punto de Control"] = df_fallas["point_id"].apply(nombre_relacion) if "point_id" in df_fallas.columns else "Sin especificar"
        conteo = df_fallas.groupby("Punto de Control").size().reset_index(name="Fallas").sort_values("Fallas", ascending=False)
        conteo["% Acumulado"] = (conteo["Fallas"].cumsum() / conteo["Fallas"].sum() * 100).round(1)

        fig_pareto = go.Figure()
        fig_pareto.add_bar(x=conteo["Punto de Control"], y=conteo["Fallas"], name="Fallas", marker_color=COLOR_PRIMARIO)
        fig_pareto.add_scatter(x=conteo["Punto de Control"], y=conteo["% Acumulado"], name="% Acumulado",
                                yaxis="y2", mode="lines+markers", line=dict(color=COLOR_TEXTO))
        fig_pareto.update_layout(
            title="Pareto de fallas de calidad por punto de control",
            yaxis=dict(title="Fallas"),
            yaxis2=dict(title="% Acumulado", overlaying="y", side="right", range=[0, 110]),
        )
        st.plotly_chart(estilizar_grafica(fig_pareto), use_container_width=True, key="grafica_pareto_calidad")
        st.dataframe(conteo, use_container_width=True, hide_index=True)
        st.caption("Regla 80/20: los puntos que juntos suman ~80% acumulado son donde conviene enfocar la mejora primero.")

    st.divider()
    st.subheader("Tendencia de producción (últimas 12 semanas)")
    df_prod_semanal = intentar(get_produccion_semanal, etiqueta="la tendencia de producción")
    if df_prod_semanal.empty:
        st.info(
            "Todavía no hay suficiente historial de órdenes cerradas para mostrar una tendencia. "
            "Esta gráfica se va llenando sola conforme Marva cierre más órdenes — en unos meses "
            "sirve como base real para planear producción por demanda estacional."
        )
    else:
        df_prod_semanal["Semana"] = df_prod_semanal["fecha"].dt.to_period("W").apply(lambda p: p.start_time.date())
        semanal = df_prod_semanal.groupby("Semana").agg(piezas=("qty_producing", "sum")).reset_index()
        fig_tend = px.line(semanal, x="Semana", y="piezas", markers=True, title="Piezas producidas por semana")
        st.plotly_chart(estilizar_grafica(fig_tend), use_container_width=True, key="grafica_tendencia_produccion")

    st.divider()
    st.subheader("Eficiencia por centro de trabajo en el tiempo")
    st.caption(
        "Como no se registran motivos de tiempo muerto, esta gráfica sirve como indicador "
        "indirecto: si la eficiencia de un centro cae de golpe, probablemente hubo paros no documentados."
    )
    df_efi = intentar(get_eficiencia_historica, etiqueta="la eficiencia histórica")
    if df_efi.empty:
        st.info("Aún no hay operaciones cerradas para calcular eficiencia histórica.")
    else:
        df_efi["Centro"] = df_efi["workcenter_id"].apply(nombre_relacion)
        df_efi["Semana"] = df_efi["fecha"].dt.to_period("W").apply(lambda p: p.start_time.date()) if df_efi["fecha"].notna().any() else "Sin fecha"
        efi_semanal = df_efi.groupby(["Semana", "Centro"]).agg(
            esperado=("duration_expected", "sum"), real=("duration", "sum")
        ).reset_index()
        efi_semanal["Eficiencia %"] = (efi_semanal["esperado"] / efi_semanal["real"].replace(0, float("nan")) * 100).round(1)
        fig_efi = px.line(efi_semanal, x="Semana", y="Eficiencia %", color="Centro", markers=True,
                           title="Eficiencia semanal por centro de trabajo")
        st.plotly_chart(estilizar_grafica(fig_efi), use_container_width=True, key="grafica_eficiencia_historica")

st.divider()
st.caption(f"Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
