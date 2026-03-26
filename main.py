from flask import Flask, render_template, request, redirect, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import functools
import base64
import math
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "barmel_secret_2026"

database_url = os.environ.get('DATABASE_URL')
if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    logger.info("Usando PostgreSQL (persistente)")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///servicios.db'
    logger.warning("DATABASE_URL no encontrada, usando SQLite (NO persistente en produccion)")

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

db = SQLAlchemy(app)

def calcular_distancia_km(gps_inicio, gps_llegada):
    try:
        lat1, lon1 = map(float, gps_inicio.split(','))
        lat2, lon2 = map(float, gps_llegada.split(','))
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distancia = R * c
        return round(distancia, 2)
    except (ValueError, AttributeError):
        return 0.0

class Tecnico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)

class Reporte(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.String(20))
    tecnico = db.Column(db.String(100))
    empresa = db.Column(db.String(100))
    km_salida = db.Column(db.Float)
    km_llegada = db.Column(db.Float)
    km_recorridos = db.Column(db.Float, default=0.0)
    h_salida_base = db.Column(db.String(20))
    h_llegada_cli = db.Column(db.String(20))
    trabajo = db.Column(db.Text)
    gps_inicio = db.Column(db.String(100))
    gps_llegada = db.Column(db.String(100))
    foto_base64 = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    logger.info("Tablas de base de datos verificadas/creadas")
    
    if Tecnico.query.count() == 0:
        iniciales = ["Marvin Doblado", "Xavier", "Rigoberto", "Tecnico Tega", "Michael Baraona"]
        for nom in iniciales:
            db.session.add(Tecnico(nombre=nom))
        db.session.commit()
        logger.info("Técnicos iniciales insertados en la base de datos.")

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'auth' not in session: return redirect('/login')
        return f(*args, **kwargs)
    return decorated

@app.route('/sw.js')
def service_worker():
    from flask import send_from_directory, make_response
    response = make_response(send_from_directory('static', 'sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/')
def index():
    tecnicos_db = Tecnico.query.order_by(Tecnico.nombre).all()
    lista = [t.nombre for t in tecnicos_db]
    return render_template('tecnico.html', lista=lista)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['user'] == 'admin' and request.form['pass'] == 'barmel2024':
            session['auth'] = True
            return redirect('/admin')
    return '<form method="post">Usuario: <input name="user"><br>Clave: <input type="password" name="pass"><br><button>Entrar</button></form>'

@app.route('/guardar', methods=['POST'])
def guardar():
    tecnico_name = request.form.get('tecnico', 'desconocido')
    empresa_name = request.form.get('empresa', 'desconocida')
    logger.info("GUARDANDO reporte: tecnico=%s, empresa=%s", tecnico_name, empresa_name)

    try:
        foto = request.files.get('foto_reporte')
        foto_b64 = ""
        import uuid
        if foto:
            upload_dir = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            filename = f"reporte_{uuid.uuid4().hex}.jpg"
            filepath = os.path.join(upload_dir, filename)
            foto.save(filepath)
            foto_b64 = f"/static/uploads/{filename}"
            logger.info("Foto guardada en disco: %s", filepath)

        gps_inicio = request.form.get('gps_inicio', '')
        gps_llegada = request.form.get('gps_llegada', '')
        km_lineal = calcular_distancia_km(gps_inicio, gps_llegada)
        
        km_realtime_str = request.form.get('km_realtime')
        if km_realtime_str:
            try:
                km = float(km_realtime_str)
                # Si el realtime es menor (ej. app suspendida), usar lineal
                if km < km_lineal:
                    km = km_lineal
            except ValueError:
                km = km_lineal
        else:
            km = km_lineal

        nuevo = Reporte(
            fecha=request.form.get('fecha'),
            tecnico=tecnico_name,
            empresa=empresa_name,
            km_salida=0,
            km_llegada=0,
            km_recorridos=km,
            h_salida_base=request.form.get('h_salida_base', '--:--'),
            h_llegada_cli=request.form.get('h_llegada_cli', '--:--'),
            trabajo=request.form.get('trabajo'),
            gps_inicio=gps_inicio,
            gps_llegada=gps_llegada,
            foto_base64=foto_b64
        )
        db.session.add(nuevo)
        db.session.commit()

        total = Reporte.query.count()
        logger.info("EXITO: Reporte #%d guardado (tecnico=%s, empresa=%s, km=%.2f). Total en BD: %d", nuevo.id, tecnico_name, empresa_name, km, total)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"ok": True, "id": nuevo.id, "km": km, "tecnico": tecnico_name, "empresa": empresa_name})

        return f"<h1>Reporte #{nuevo.id} Guardado</h1><p>Distancia calculada por GPS: {km} KM</p><a href='/'>Volver al inicio</a>"

    except Exception as e:
        db.session.rollback()
        logger.error("ERROR al guardar reporte (tecnico=%s, empresa=%s): %s", tecnico_name, empresa_name, str(e))
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"ok": False, "error": str(e)}), 500
        return f"<h1>Error al guardar</h1><p>{str(e)}</p><a href='/'>Volver</a>", 500

@app.route('/admin')
@login_required
def admin():
    reportes = Reporte.query.order_by(Reporte.id.desc()).all()
    hace_una_semana = datetime.utcnow() - timedelta(days=7)
    reportes_semana = Reporte.query.filter(Reporte.timestamp >= hace_una_semana).all()
    km_semana = 0.0
    for r in reportes_semana:
        if r.km_recorridos and r.km_recorridos > 0:
            km_semana += r.km_recorridos
        else:
            km_semana += (r.km_llegada or 0) - (r.km_salida or 0)
    km_semana = round(km_semana, 2)

    from sqlalchemy import func
    resultados = db.session.query(
        Reporte.tecnico,
        func.coalesce(func.sum(Reporte.km_recorridos), 0).label('total_km'),
        func.count(Reporte.id).label('total_visitas')
    ).group_by(Reporte.tecnico).order_by(func.sum(Reporte.km_recorridos).desc()).all()

    km_por_tecnico = [
        {"nombre": r.tecnico, "total_km": round(float(r.total_km), 2), "total_visitas": r.total_visitas}
        for r in resultados
    ]

    logger.info("ADMIN: mostrando %d reportes, KM semana=%.2f, tecnicos=%d", len(reportes), km_semana, len(km_por_tecnico))
    return render_template('admin.html', reportes=reportes, total_km=km_semana, km_por_tecnico=km_por_tecnico)

@app.route('/admin/tecnicos', methods=['GET', 'POST'])
@login_required
def admin_tecnicos():
    if request.method == 'POST':
        nombre_nuevo = request.form.get('nombre', '').strip()
        if nombre_nuevo:
            existe = Tecnico.query.filter_by(nombre=nombre_nuevo).first()
            if not existe:
                db.session.add(Tecnico(nombre=nombre_nuevo))
                db.session.commit()
                logger.info("Nuevo tecnico creado: %s", nombre_nuevo)
        return redirect('/admin/tecnicos')
        
    tecnicos = Tecnico.query.order_by(Tecnico.nombre).all()
    return render_template('tecnicos_admin.html', tecnicos=tecnicos)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
