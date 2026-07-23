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

import xmlrpc.client
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
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
def conectar_odoo():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise ConnectionError("No se pudo autenticar en Odoo. Revisa usuario/contraseña/DB.")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
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
def get_centros_trabajo():
    uid, models = conectar_odoo()
    campos = ["name", "costs_hour", "working_state"]
    data = buscar_leer(models, uid, "mrp.workcenter", [], campos)
    return pd.DataFrame(data)


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
    """Costo de materiales según receta (BOM), escalado a la cantidad a producir de cada orden."""
    if df_ordenes.empty:
        return pd.DataFrame()
    uid, models = conectar_odoo()
    bom_ids = df_ordenes["bom_id"].dropna().apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x).unique().tolist()
    if not bom_ids:
        return pd.DataFrame()

    boms = buscar_leer(models, uid, "mrp.bom", [("id", "in", bom_ids)], ["id", "product_qty"])
    df_boms = pd.DataFrame(boms).rename(columns={"id": "bom_id", "product_qty": "bom_cantidad_base"})

    lineas = buscar_leer(models, uid, "mrp.bom.line", [("bom_id", "in", bom_ids)], ["bom_id", "product_id", "product_qty"])
    df_lineas = pd.DataFrame(lineas)
    if df_lineas.empty:
        return pd.DataFrame()
    df_lineas["bom_id"] = df_lineas["bom_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df_lineas["producto_id"] = df_lineas["product_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)

    product_ids = df_lineas["producto_id"].unique().tolist()
    precios = buscar_leer(models, uid, "product.product", [("id", "in", product_ids)], ["standard_price"])
    df_precios = pd.DataFrame(precios).rename(columns={"id": "producto_id", "standard_price": "costo_unitario"})

    df_lineas = df_lineas.merge(df_precios, on="producto_id", how="left")
    df_lineas = df_lineas.merge(df_boms, on="bom_id", how="left")
    df_lineas["costo_linea"] = df_lineas["product_qty"] * df_lineas["costo_unitario"].fillna(0)

    costo_bom = df_lineas.groupby("bom_id").agg(
        costo_por_lote=("costo_linea", "sum"),
        cantidad_base=("bom_cantidad_base", "first"),
    ).reset_index()
    costo_bom["costo_unitario_bom"] = costo_bom["costo_por_lote"] / costo_bom["cantidad_base"].replace(0, 1)

    ordenes = df_ordenes.copy()
    ordenes["bom_id"] = ordenes["bom_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    ordenes = ordenes.merge(costo_bom, on="bom_id", how="left")
    ordenes["costo_planeado"] = ordenes["costo_unitario_bom"].fillna(0) * ordenes["product_qty"]
    return ordenes[["id", "name", "costo_planeado"]]


def get_costo_mano_obra(df_workorders, df_centros):
    """Costo real de mano de obra: minutos reales / 60 * costo-hora del centro de trabajo."""
    if df_workorders.empty or df_centros.empty:
        return pd.DataFrame()
    wo = df_workorders.copy()
    wo["centro_id"] = wo["workcenter_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    wo["orden_id"] = wo["production_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    wo["orden"] = wo["production_id"].apply(nombre_relacion)

    centros = df_centros.rename(columns={"id": "centro_id", "costs_hour": "costo_hora"})[["centro_id", "costo_hora"]]
    wo = wo.merge(centros, on="centro_id", how="left")
    wo["costo_mano_obra"] = (wo["duration"] / 60.0) * wo["costo_hora"].fillna(0)
    return wo.groupby(["orden_id", "orden"]).agg(costo_mano_obra=("costo_mano_obra", "sum")).reset_index()


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
df_costo_planeado = intentar(get_costo_planeado_materiales, df_ordenes, etiqueta="el costo planeado (BOM)")
df_costo_mo = get_costo_mano_obra(df_workorders, df_centros)

costo_material_planeado_total = df_costo_planeado["costo_planeado"].sum() if not df_costo_planeado.empty else 0
costo_mano_obra_total = df_costo_mo["costo_mano_obra"].sum() if not df_costo_mo.empty else 0
costo_total_produccion = costo_material_planeado_total + costo_mano_obra_total
piezas_producidas_total = df_ordenes["qty_producing"].sum() if not df_ordenes.empty else 0
costo_por_pieza = (costo_total_produccion / piezas_producidas_total) if piezas_producidas_total else 0

# ---------- KPIs ----------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Órdenes en progreso", len(df_ordenes[df_ordenes["state"] == "progress"]) if not df_ordenes.empty else 0)
k2.metric("Órdenes planeadas/confirmadas", len(df_ordenes[df_ordenes["state"].isin(["confirmed", "planned"])]) if not df_ordenes.empty else 0)
k3.metric("Órdenes atrasadas", len(df_atrasadas))
k4.metric("Terminadas hoy", len(df_terminadas_hoy))
k5.metric("Alertas de calidad abiertas", len(df_calidad))

k6, k7, k8, k9 = st.columns(4)
k6.metric("Costo materiales (BOM)", f"${costo_material_planeado_total:,.0f}")
k7.metric("Costo mano de obra (real)", f"${costo_mano_obra_total:,.0f}")
k8.metric("Costo total de producción", f"${costo_total_produccion:,.0f}")
k9.metric("Costo total por pieza", f"${costo_por_pieza:,.2f}" if piezas_producidas_total else "N/A")

st.divider()

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📋 Órdenes en piso", "⚙️ Centros de trabajo", "⏱️ Horas y avance",
    "💰 Costos", "✅ Calidad", "📦 Terminadas hoy", "📊 Acumulado por periodo",
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
        st.plotly_chart(estilizar_grafica(fig), use_container_width=True)

        if not df_centros.empty:
            st.dataframe(
                df_centros.rename(columns={"name": "Centro", "costs_hour": "Costo/Hora", "working_state": "Estado Actual"}),
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
            comparativa["Min. Esperados"] / comparativa["Min. Reales"].replace(0, pd.NA) * 100
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
        "inventario real se controla en otro sistema. Mano de obra = horas reales del "
        "workorder × costo-hora del centro de trabajo (máquina + operador) configurado en Odoo."
    )
    if df_costo_planeado.empty and df_costo_mo.empty:
        st.info("Aún no hay órdenes con receta (BOM) o tiempos registrados.")
    else:
        resumen = df_costo_planeado.rename(columns={"id": "orden_id", "name": "orden"}) if not df_costo_planeado.empty else pd.DataFrame(columns=["orden_id", "orden", "costo_planeado"])
        if not df_costo_mo.empty:
            resumen = resumen.merge(df_costo_mo, on=["orden_id", "orden"], how="outer")
        resumen = resumen.fillna(0)
        resumen["costo_total"] = resumen.get("costo_planeado", 0) + resumen.get("costo_mano_obra", 0)

        if not df_ordenes.empty:
            piezas = df_ordenes[["id", "qty_producing"]].rename(columns={"id": "orden_id"})
            resumen = resumen.merge(piezas, on="orden_id", how="left")
            resumen["qty_producing"] = resumen["qty_producing"].fillna(0)
            resumen["costo_por_pieza"] = resumen.apply(
                lambda r: r["costo_total"] / r["qty_producing"] if r["qty_producing"] > 0 else None, axis=1
            )

        tabla_costos = resumen.rename(columns={
            "orden": "Orden", "costo_planeado": "Materiales (BOM)",
            "costo_mano_obra": "Mano de Obra", "costo_total": "Costo Total",
            "qty_producing": "Piezas Producidas", "costo_por_pieza": "Costo por Pieza",
        }).drop(columns=["orden_id"], errors="ignore")
        st.dataframe(tabla_costos, use_container_width=True, hide_index=True)

        st.markdown("**Desglose de mano de obra por centro de trabajo**")
        if not df_workorders.empty and not df_centros.empty:
            wo = df_workorders.copy()
            wo["Centro"] = wo["workcenter_id"].apply(nombre_relacion)
            centros_costo = df_centros.rename(columns={"id": "centro_id", "costs_hour": "costo_hora"})
            wo["centro_id"] = wo["workcenter_id"].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
            wo = wo.merge(centros_costo[["centro_id", "costo_hora"]], on="centro_id", how="left")
            wo["costo"] = (wo["duration"] / 60.0) * wo["costo_hora"].fillna(0)
            por_centro = wo.groupby("Centro").agg(
                horas_reales=("duration", lambda s: s.sum() / 60.0), costo=("costo", "sum")
            ).reset_index()
            fig_centro = px.bar(por_centro, x="Centro", y="costo", title="Costo de mano de obra por centro de trabajo")
            st.plotly_chart(estilizar_grafica(fig_centro), use_container_width=True)
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
        costo_mat_periodo = intentar(get_costo_planeado_materiales, df_periodo, etiqueta="el costo de materiales del periodo")
        costo_mo_periodo = get_costo_mano_obra(wo_periodo, df_centros)

        total_mat = costo_mat_periodo["costo_planeado"].sum() if not costo_mat_periodo.empty else 0
        total_mo = costo_mo_periodo["costo_mano_obra"].sum() if not costo_mo_periodo.empty else 0
        total_costo = total_mat + total_mo
        total_piezas = df_periodo["qty_producing"].sum()
        costo_pieza_prom = (total_costo / total_piezas) if total_piezas else 0

        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Órdenes cerradas", len(df_periodo))
        p2.metric("Piezas producidas", f"{total_piezas:,.0f}")
        p3.metric("Costo materiales (BOM)", f"${total_mat:,.0f}")
        p4.metric("Costo mano de obra", f"${total_mo:,.0f}")
        p5.metric("Costo por pieza (prom.)", f"${costo_pieza_prom:,.2f}" if total_piezas else "N/A")

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
        st.plotly_chart(estilizar_grafica(fig_dia), use_container_width=True)

st.divider()
st.caption(f"Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
