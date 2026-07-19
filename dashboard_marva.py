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
# CONFIGURACIÓN
# ============================================================
st.set_page_config(
    page_title="Dashboard de Piso - Marva",
    layout="wide",
    page_icon="🏭",
)

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


# ============================================================
# EXTRACCIÓN DE DATOS (con caché corta para no saturar Odoo)
# ============================================================
@st.cache_data(ttl=30, show_spinner=False)
def get_ordenes_fabricacion():
    """Órdenes de fabricación (mrp.production) activas y recientes."""
    uid, models = conectar_odoo()
    campos = [
        "name", "product_id", "product_qty", "qty_producing",
        "state", "date_planned_start", "date_planned_finished",
        "date_start", "date_finished", "origin",
        "user_id", "company_id", "bom_id", "workorder_ids",
    ]
    dominio = [("state", "in", ["confirmed", "progress", "to_close", "planned"])]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos, orden="date_planned_start asc")
    return pd.DataFrame(data)


@st.cache_data(ttl=30, show_spinner=False)
def get_ordenes_terminadas_hoy():
    uid, models = conectar_odoo()
    hoy = datetime.now().strftime("%Y-%m-%d 00:00:00")
    campos = ["name", "product_id", "product_qty", "qty_producing", "date_finished", "state"]
    dominio = [("state", "=", "done"), ("date_finished", ">=", hoy)]
    data = buscar_leer(models, uid, "mrp.production", dominio, campos)
    return pd.DataFrame(data)


@st.cache_data(ttl=30, show_spinner=False)
def get_workorders(orden_ids):
    """Órdenes de trabajo (mrp.workorder): quién, en qué centro, cuánto tiempo lleva."""
    if not orden_ids:
        return pd.DataFrame()
    uid, models = conectar_odoo()
    campos = [
        "name", "production_id", "workcenter_id", "state",
        "duration_expected", "duration", "date_start", "date_finished",
    ]
    dominio = [("production_id", "in", orden_ids)]
    data = buscar_leer(models, uid, "mrp.workorder", dominio, campos)
    return pd.DataFrame(data)


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


# ============================================================
# UI
# ============================================================
st.title("🏭 Dashboard de Piso — Marva Silos y Construcción")
st.caption("Datos en vivo desde Odoo · Actualiza automáticamente cada 30 segundos")

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

df_ordenes = get_ordenes_fabricacion()
df_terminadas_hoy = get_ordenes_terminadas_hoy()
df_atrasadas = get_ordenes_atrasadas(df_ordenes)

if not df_ordenes.empty:
    orden_ids = df_ordenes["id"].tolist()
    df_workorders = get_workorders(orden_ids)
else:
    df_workorders = pd.DataFrame()

df_centros = get_centros_trabajo()
df_calidad = get_alertas_calidad()

# ---------- Costos ----------
df_consumo = get_consumo_materiales(orden_ids) if not df_ordenes.empty else pd.DataFrame()
df_costo_planeado = get_costo_planeado_materiales(df_ordenes)
df_costo_mo = get_costo_mano_obra(df_workorders, df_centros)

costo_material_real_total = df_consumo["costo_real"].sum() if not df_consumo.empty else 0
costo_material_planeado_total = df_costo_planeado["costo_planeado"].sum() if not df_costo_planeado.empty else 0
costo_mano_obra_total = df_costo_mo["costo_mano_obra"].sum() if not df_costo_mo.empty else 0
costo_total_produccion = costo_material_real_total + costo_mano_obra_total
desviacion_material_pct = (
    ((costo_material_real_total - costo_material_planeado_total) / costo_material_planeado_total * 100)
    if costo_material_planeado_total else 0
)

# ---------- KPIs ----------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Órdenes en progreso", len(df_ordenes[df_ordenes["state"] == "progress"]) if not df_ordenes.empty else 0)
k2.metric("Órdenes planeadas/confirmadas", len(df_ordenes[df_ordenes["state"].isin(["confirmed", "planned"])]) if not df_ordenes.empty else 0)
k3.metric("Órdenes atrasadas", len(df_atrasadas))
k4.metric("Terminadas hoy", len(df_terminadas_hoy))
k5.metric("Alertas de calidad abiertas", len(df_calidad))

k6, k7, k8, k9 = st.columns(4)
k6.metric("Costo materiales (real)", f"${costo_material_real_total:,.0f}")
k7.metric("Costo mano de obra (real)", f"${costo_mano_obra_total:,.0f}")
k8.metric("Costo total de producción", f"${costo_total_produccion:,.0f}")
k9.metric("Desviación vs. costo BOM", f"{desviacion_material_pct:+.1f}%",
          delta=f"{desviacion_material_pct:+.1f}%", delta_color="inverse")

st.divider()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📋 Órdenes en piso", "⚙️ Centros de trabajo", "⏱️ Horas y avance",
    "💰 Costos", "✅ Calidad", "📦 Terminadas hoy",
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
        st.plotly_chart(fig, use_container_width=True)

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
    st.subheader("Costo real vs. costo planeado (BOM) por orden")
    st.caption(
        "El costo real de materiales usa el costo estándar del producto (standard_price) "
        "al momento de consultar — es una buena aproximación, pero si Marva usa costeo FIFO "
        "o promedio ponderado, el valor contable exacto puede diferir un poco."
    )
    if df_consumo.empty and df_costo_planeado.empty:
        st.info("Aún no hay consumo de materiales registrado en las órdenes activas.")
    else:
        resumen_real = (
            df_consumo.groupby(["orden_id", "orden"]).agg(costo_material_real=("costo_real", "sum")).reset_index()
            if not df_consumo.empty else pd.DataFrame(columns=["orden_id", "orden", "costo_material_real"])
        )
        resumen = df_costo_planeado.rename(columns={"id": "orden_id", "name": "orden"}) if not df_costo_planeado.empty else pd.DataFrame(columns=["orden_id", "orden", "costo_planeado"])
        resumen = resumen.merge(resumen_real, on=["orden_id", "orden"], how="outer")
        if not df_costo_mo.empty:
            resumen = resumen.merge(df_costo_mo, on=["orden_id", "orden"], how="outer")
        resumen = resumen.fillna(0)
        resumen["costo_total_real"] = resumen.get("costo_material_real", 0) + resumen.get("costo_mano_obra", 0)
        resumen["desviacion_%"] = (
            (resumen.get("costo_material_real", 0) - resumen.get("costo_planeado", 0))
            / resumen.get("costo_planeado", pd.Series([1] * len(resumen))).replace(0, 1) * 100
        ).round(1)

        tabla_costos = resumen.rename(columns={
            "orden": "Orden", "costo_planeado": "Materiales Planeado (BOM)",
            "costo_material_real": "Materiales Real", "costo_mano_obra": "Mano de Obra Real",
            "costo_total_real": "Costo Total Real", "desviacion_%": "Desviación Materiales %",
        }).drop(columns=["orden_id"], errors="ignore")
        st.dataframe(tabla_costos, use_container_width=True, hide_index=True)

        if not df_consumo.empty:
            st.markdown("**Top materiales consumidos (todas las órdenes activas)**")
            top_materiales = df_consumo.groupby("Producto").agg(
                cantidad=("cantidad", "sum"), costo=("costo_real", "sum")
            ).reset_index().sort_values("costo", ascending=False).head(10)
            fig_mat = px.bar(top_materiales, x="Producto", y="costo", title="Costo de materiales por producto")
            st.plotly_chart(fig_mat, use_container_width=True)

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

st.divider()
st.caption(f"Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
