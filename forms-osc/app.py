import os
import re
import uuid
import json
import time
import sqlite3
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, jsonify, send_from_directory, g, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')

# ============================================================
# CONFIGURAÇÃO
# ============================================================

APP_SECRET = 'tao-doce-quanto-ella-secret-2024'
ADMIN_PASSWORD = 'ella2026'

app.config['SECRET_KEY'] = APP_SECRET
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB (mídia da confeitaria)
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'webp', 'mp4', 'webm', 'mov'}

# Bancos separados
DOCERIA_DATABASE = 'doceria.db'
FORMS_DATABASE = 'forms.db'

# SharePoint / Microsoft Graph (usado só pelas rotas de formulários OSC)
TENANT_ID = "4c6e6c4e-0dfe-4318-b8c4-de55d5d0f18b"
CLIENT_ID = "efba2710-4ba7-40c1-9ed7-cbc8937be730"
CLIENT_SECRET = "vXX8Q~rfZl9hYBD_gc1yPNZyCZeL~Q2xBq5OJaRE"

SHAREPOINT_SITE_ID = (
    "inrbb.sharepoint.com,a251f832-1219-4909-b1a4-b3491fad9200,"
    "b76790fc-110a-49dd-8372-0664a36f2acf"
)
SHAREPOINT_DRIVE_ID = (
    "b!MvhRohkSCUmxpLNJH62SAPyQZ7cKEd1Jg3IGZKNvKs_XNOWCSrnxRIPOaOTl2Hvk"
)
SHAREPOINT_ROOT_FOLDER = "Documentos Compartilhados"

# Painel principal (validação de admin global para as rotas de formulários)
MAIN_SYSTEM_API_URL = "https://erickmth.pythonanywhere.com"

_token_cache = {"access_token": None, "expires_at": 0}


# ============================================================
# DATABASE - DOCERIA
# ============================================================

def get_doceria_db():
    db = getattr(g, '_doceria_database', None)
    if db is None:
        db = g._doceria_database = sqlite3.connect(DOCERIA_DATABASE, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA journal_mode = WAL')
    return db


# ============================================================
# DATABASE - FORMS
# ============================================================

def get_forms_db():
    db = getattr(g, '_forms_database', None)
    if db is None:
        db = g._forms_database = sqlite3.connect(FORMS_DATABASE, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA journal_mode = WAL')
    return db


@app.teardown_appcontext
def close_connection(exception):
    doceria_db = getattr(g, '_doceria_database', None)
    if doceria_db is not None:
        doceria_db.close()
    
    forms_db = getattr(g, '_forms_database', None)
    if forms_db is not None:
        forms_db.close()


def init_doceria_db():
    with app.app_context():
        db = get_doceria_db()
        db.executescript('''
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                descricao TEXT,
                preco REAL NOT NULL,
                imagem TEXT,
                categoria TEXT DEFAULT 'geral',
                tipo_media TEXT DEFAULT 'image',
                ativo INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS configuracoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                whatsapp TEXT DEFAULT '',
                instagram TEXT DEFAULT '',
                endereco TEXT DEFAULT '',
                horario_funcionamento TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS subcategorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS produto_subcategorias (
                produto_id INTEGER NOT NULL,
                subcategoria_id INTEGER NOT NULL,
                FOREIGN KEY (produto_id) REFERENCES produtos(id) ON DELETE CASCADE,
                FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id) ON DELETE CASCADE,
                PRIMARY KEY (produto_id, subcategoria_id)
            );
        ''')

        # Seed configurações padrão
        existing = db.execute('SELECT COUNT(*) as c FROM configuracoes').fetchone()
        if existing['c'] == 0:
            db.execute('''INSERT INTO configuracoes (whatsapp, instagram, endereco, horario_funcionamento)
                          VALUES (?, ?, ?, ?)''',
                       ('5511999999999', '@taodocequeella',
                        'Rua das Flores, 123 – Bairro Jardim', 'Seg a Sex: 9h–18h | Sáb: 9h–14h'))

        # Seed subcategorias padrão
        subcats = db.execute('SELECT COUNT(*) as c FROM subcategorias').fetchone()
        if subcats['c'] == 0:
            subcat_seed = ['Premium', 'Dia dos Namorados', 'Festa Infantil', 'Vegano', 'Sem Glúten', 'Edição Limitada']
            for sc in subcat_seed:
                db.execute('INSERT INTO subcategorias (nome) VALUES (?)', (sc,))

        # Seed produtos de exemplo
        count = db.execute('SELECT COUNT(*) as c FROM produtos').fetchone()
        if count['c'] == 0:
            produtos_seed = [
                ('Brigadeiro Gourmet', 'Brigadeiro artesanal com granulado crocante, produzido com ingredientes de qualidade', 6.50, None, 'Docinhos', 'image'),
                ('Bolo de Pote Ninho', 'Camadas de bolo fofinho com creme de leite ninho e morangos frescos', 18.00, None, 'Bolos', 'image'),
                ('Trufa de Maracujá', 'Trufa cremosa de chocolate branco com recheio de maracujá', 8.00, None, 'Docinhos', 'image'),
                ('Caixa de Doces Sortidos', 'Caixa com 12 doces finos artesanais para presentear', 75.00, None, 'Docinhos', 'image'),
                ('Bolo de Pote Red Velvet', 'Clássico red velvet em pote individual com cream cheese', 20.00, None, 'Bolos', 'image'),
                ('Brownie', 'Brownie intenso de cacau com recheio de doce de leite', 14.00, None, 'Brownies', 'image'),
                ('Cookie Red Velvet', 'Cookie macio com gotas de chocolate e toque de red velvet', 9.00, None, 'Cookies', 'image'),
                ('Casadinho de Leite Ninho', 'Casadinho recheado com creme de leite ninho e cobertura de chocolate', 7.50, None, 'Casadinhos', 'image'),
                ('Chocolate Quente', 'Chocolate quente cremoso e aveludado, produzido com ingredientes cuidadosamente escolhidos', 15.00, None, 'Bebidas', 'image'),
                ('Coxinha', 'Coxinha de frango com catupiry, massa macia e crocante', 8.00, None, 'Salgados', 'image'),
                ('Torta de Limão', 'Torta com base de biscoito, mousse de limão e merengue', 22.00, None, 'Tortas', 'image'),
                ('Pudim de Leite', 'Pudim cremoso com calda de caramelo', 18.00, None, 'Pudim', 'image'),
                ('Palha Italiana', 'Palha italiana crocante com cobertura de chocolate', 6.00, None, 'Palha italiana', 'image'),
                ('Cone Trufado', 'Cone recheado com trufa de chocolate e cobertura', 10.00, None, 'Cones', 'image'),
            ]
            for p in produtos_seed:
                db.execute('INSERT INTO produtos (nome, descricao, preco, imagem, categoria, tipo_media) VALUES (?,?,?,?,?,?)', p)

        db.commit()


def init_forms_db():
    with app.app_context():
        db = get_forms_db()
        db.executescript('''
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                image_data TEXT,
                is_active INTEGER DEFAULT 0,
                folder_name_question_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                form_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                description TEXT DEFAULT '',
                type TEXT NOT NULL,
                is_required INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                options TEXT,
                file_config TEXT,
                use_for_folder_name INTEGER DEFAULT 0,
                file_label TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                form_id INTEGER NOT NULL,
                folder_name TEXT,
                folder_id TEXT,
                submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                response_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                answer TEXT,
                FOREIGN KEY (response_id) REFERENCES responses(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                response_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                original_name TEXT,
                stored_name TEXT,
                sharepoint_item_id TEXT,
                sharepoint_folder_id TEXT,
                web_url TEXT,
                file_size INTEGER,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (response_id) REFERENCES responses(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
            );
        ''')

        # Migração para bancos criados antes da coluna image_data existir.
        try:
            db.execute("ALTER TABLE forms ADD COLUMN image_data TEXT")
        except sqlite3.OperationalError:
            pass

        db.commit()


# ============================================================
# HELPERS GERAIS
# ============================================================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def row_to_dict(row):
    return dict(row) if row else None


def check_admin(password):
    return bool(password) and password == ADMIN_PASSWORD


# ============================================================
# CORS (idêntico ao app.py da confeitaria que já funcionava)
# ============================================================

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-Admin-Password'
    response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition'
    return response


@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    return jsonify({}), 200


# ============================================================
# AUTH - CONFEITARIA (senha compartilhada, como antes)
# ============================================================

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        password = request.headers.get('X-Admin-Password') or request.args.get('password')
        if not check_admin(password):
            return jsonify({'error': 'Não autorizado'}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    if check_admin(data.get('password', '')):
        return jsonify({'success': True, 'token': ADMIN_PASSWORD})
    return jsonify({'error': 'Senha incorreta'}), 401


# ============================================================
# AUTH - FORMULÁRIOS OSC (JWT validado no sistema principal)
# ============================================================

def require_global_admin_jwt(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or len(auth_header) <= 7:
            return jsonify({"error": "Token não fornecido"}), 401

        try:
            resp = requests.get(
                f"{MAIN_SYSTEM_API_URL}/api/admin/permissions",
                headers={"Authorization": auth_header},
                timeout=10,
            )
        except requests.RequestException:
            return jsonify({
                "error": "Não foi possível validar a sessão no momento. Tente novamente."
            }), 503

        if resp.status_code == 401:
            return jsonify({"error": "Sessão expirada ou inválida"}), 401
        if not resp.ok:
            return jsonify({"error": "Não foi possível validar a sessão."}), 502

        try:
            data = resp.json()
        except ValueError:
            return jsonify({"error": "Resposta inválida do sistema de autenticação."}), 502

        if data.get("tipo_admin") != "global":
            return jsonify({"error": "Acesso negado - apenas administrador global"}), 403

        request.global_admin_username = data.get("username")
        return fn(*args, **kwargs)
    return wrapped


# ============================================================
# CONFEITARIA - PRODUTOS (rotas originais, inalteradas)
# ============================================================

@app.route('/api/produtos', methods=['GET'])
def get_produtos():
    db = get_doceria_db()
    admin = request.headers.get('X-Admin-Password') == ADMIN_PASSWORD
    if admin:
        rows = db.execute('SELECT * FROM produtos ORDER BY created_at DESC').fetchall()
    else:
        rows = db.execute('SELECT * FROM produtos WHERE ativo=1 ORDER BY created_at DESC').fetchall()

    produtos_list = []
    for row in rows:
        p = dict(row)
        subcats = db.execute('''
            SELECT s.id, s.nome FROM subcategorias s
            INNER JOIN produto_subcategorias ps ON ps.subcategoria_id = s.id
            WHERE ps.produto_id = ?
        ''', (p['id'],)).fetchall()
        p['subcategorias'] = [{'id': sc['id'], 'nome': sc['nome']} for sc in subcats]
        produtos_list.append(p)

    return jsonify(produtos_list)


@app.route('/api/produtos/<int:pid>', methods=['GET'])
def get_produto(pid):
    db = get_doceria_db()
    row = db.execute('SELECT * FROM produtos WHERE id=?', (pid,)).fetchone()
    if not row:
        return jsonify({'error': 'Produto não encontrado'}), 404

    p = dict(row)
    subcats = db.execute('''
        SELECT s.id, s.nome FROM subcategorias s
        INNER JOIN produto_subcategorias ps ON ps.subcategoria_id = s.id
        WHERE ps.produto_id = ?
    ''', (pid,)).fetchall()
    p['subcategorias'] = [{'id': sc['id'], 'nome': sc['nome']} for sc in subcats]

    return jsonify(p)


@app.route('/api/produtos', methods=['POST'])
@require_admin
def create_produto():
    db = get_doceria_db()
    nome = request.form.get('nome', '').strip()
    descricao = request.form.get('descricao', '').strip()
    preco_str = request.form.get('preco', '0')
    categoria = request.form.get('categoria', 'geral').strip()
    tipo_media = request.form.get('tipo_media', 'image').strip()

    if not nome:
        return jsonify({'error': 'Nome é obrigatório'}), 400
    try:
        preco = float(preco_str.replace(',', '.'))
    except ValueError:
        return jsonify({'error': 'Preço inválido'}), 400

    imagem = None
    if 'imagem' in request.files:
        file = request.files['imagem']
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            imagem = filename

    cur = db.execute(
        'INSERT INTO produtos (nome, descricao, preco, imagem, categoria, tipo_media) VALUES (?,?,?,?,?,?)',
        (nome, descricao, preco, imagem, categoria, tipo_media)
    )
    produto_id = cur.lastrowid

    subcategorias_ids = request.form.getlist('subcategorias')
    for sc_id in subcategorias_ids:
        if sc_id:
            db.execute('INSERT INTO produto_subcategorias (produto_id, subcategoria_id) VALUES (?, ?)',
                      (produto_id, int(sc_id)))

    db.commit()
    row = db.execute('SELECT * FROM produtos WHERE id=?', (produto_id,)).fetchone()
    p = dict(row)
    subcats = db.execute('''
        SELECT s.id, s.nome FROM subcategorias s
        INNER JOIN produto_subcategorias ps ON ps.subcategoria_id = s.id
        WHERE ps.produto_id = ?
    ''', (produto_id,)).fetchall()
    p['subcategorias'] = [{'id': sc['id'], 'nome': sc['nome']} for sc in subcats]

    return jsonify(p), 201


@app.route('/api/produtos/<int:pid>', methods=['PUT'])
@require_admin
def update_produto(pid):
    db = get_doceria_db()
    row = db.execute('SELECT * FROM produtos WHERE id=?', (pid,)).fetchone()
    if not row:
        return jsonify({'error': 'Produto não encontrado'}), 404

    nome = request.form.get('nome', row['nome']).strip()
    descricao = request.form.get('descricao', row['descricao'] or '').strip()
    preco_str = request.form.get('preco', str(row['preco']))
    categoria = request.form.get('categoria', row['categoria']).strip()
    tipo_media = request.form.get('tipo_media', row['tipo_media']).strip()
    ativo_str = request.form.get('ativo', str(row['ativo']))
    ativo = 1 if str(ativo_str) in ('1', 'true', 'True') else 0

    try:
        preco = float(preco_str.replace(',', '.'))
    except ValueError:
        return jsonify({'error': 'Preço inválido'}), 400

    imagem = row['imagem']
    if 'imagem' in request.files:
        file = request.files['imagem']
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            if row['imagem'] and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], row['imagem'])):
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], row['imagem']))
                except Exception:
                    pass
            imagem = filename

    db.execute(
        'UPDATE produtos SET nome=?, descricao=?, preco=?, imagem=?, categoria=?, tipo_media=?, ativo=? WHERE id=?',
        (nome, descricao, preco, imagem, categoria, tipo_media, ativo, pid)
    )

    db.execute('DELETE FROM produto_subcategorias WHERE produto_id=?', (pid,))
    subcategorias_ids = request.form.getlist('subcategorias')
    for sc_id in subcategorias_ids:
        if sc_id:
            db.execute('INSERT INTO produto_subcategorias (produto_id, subcategoria_id) VALUES (?, ?)',
                      (pid, int(sc_id)))

    db.commit()
    updated = db.execute('SELECT * FROM produtos WHERE id=?', (pid,)).fetchone()
    p = dict(updated)
    subcats = db.execute('''
        SELECT s.id, s.nome FROM subcategorias s
        INNER JOIN produto_subcategorias ps ON ps.subcategoria_id = s.id
        WHERE ps.produto_id = ?
    ''', (pid,)).fetchall()
    p['subcategorias'] = [{'id': sc['id'], 'nome': sc['nome']} for sc in subcats]

    return jsonify(p)


@app.route('/api/produtos/<int:pid>/toggle', methods=['POST'])
@require_admin
def toggle_produto(pid):
    db = get_doceria_db()
    row = db.execute('SELECT * FROM produtos WHERE id=?', (pid,)).fetchone()
    if not row:
        return jsonify({'error': 'Produto não encontrado'}), 404
    novo = 0 if row['ativo'] == 1 else 1
    db.execute('UPDATE produtos SET ativo=? WHERE id=?', (novo, pid))
    db.commit()
    return jsonify({'ativo': novo})


@app.route('/api/produtos/<int:pid>', methods=['DELETE'])
@require_admin
def delete_produto(pid):
    db = get_doceria_db()
    try:
        row = db.execute('SELECT * FROM produtos WHERE id=?', (pid,)).fetchone()
        if not row:
            return jsonify({'error': 'Produto não encontrado'}), 404

        if row['imagem']:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], row['imagem'])
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Erro ao remover arquivo: {e}")

        db.execute('DELETE FROM produtos WHERE id=?', (pid,))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Erro ao excluir produto {pid}: {e}")
        db.rollback()
        return jsonify({'error': f'Erro ao excluir produto: {str(e)}'}), 500


# ============================================================
# CONFEITARIA - SUBCATEGORIAS
# ============================================================

@app.route('/api/subcategorias', methods=['GET'])
def get_subcategorias():
    db = get_doceria_db()
    rows = db.execute('SELECT * FROM subcategorias ORDER BY nome').fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route('/api/subcategorias', methods=['POST'])
@require_admin
def create_subcategoria():
    db = get_doceria_db()
    data = request.get_json() or {}
    nome = data.get('nome', '').strip()
    if not nome:
        return jsonify({'error': 'Nome é obrigatório'}), 400

    try:
        cur = db.execute('INSERT INTO subcategorias (nome) VALUES (?)', (nome,))
        db.commit()
        row = db.execute('SELECT * FROM subcategorias WHERE id=?', (cur.lastrowid,)).fetchone()
        return jsonify(row_to_dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Subcategoria já existe'}), 400


@app.route('/api/subcategorias/<int:scid>', methods=['PUT'])
@require_admin
def update_subcategoria(scid):
    db = get_doceria_db()
    data = request.get_json() or {}
    nome = data.get('nome', '').strip()
    if not nome:
        return jsonify({'error': 'Nome é obrigatório'}), 400

    row = db.execute('SELECT * FROM subcategorias WHERE id=?', (scid,)).fetchone()
    if not row:
        return jsonify({'error': 'Subcategoria não encontrada'}), 404

    try:
        db.execute('UPDATE subcategorias SET nome=? WHERE id=?', (nome, scid))
        db.commit()
        updated = db.execute('SELECT * FROM subcategorias WHERE id=?', (scid,)).fetchone()
        return jsonify(row_to_dict(updated))
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Subcategoria já existe'}), 400


@app.route('/api/subcategorias/<int:scid>', methods=['DELETE'])
@require_admin
def delete_subcategoria(scid):
    db = get_doceria_db()
    row = db.execute('SELECT * FROM subcategorias WHERE id=?', (scid,)).fetchone()
    if not row:
        return jsonify({'error': 'Subcategoria não encontrada'}), 404

    db.execute('DELETE FROM produto_subcategorias WHERE subcategoria_id=?', (scid,))
    db.execute('DELETE FROM subcategorias WHERE id=?', (scid,))
    db.commit()
    return jsonify({'success': True})


# ============================================================
# CONFEITARIA - CONFIGURAÇÕES / STATS
# ============================================================

@app.route('/api/configuracoes', methods=['GET'])
def get_configuracoes():
    db = get_doceria_db()
    row = db.execute('SELECT * FROM configuracoes LIMIT 1').fetchone()
    return jsonify(row_to_dict(row) if row else {})


@app.route('/api/configuracoes', methods=['PUT'])
@require_admin
def update_configuracoes():
    db = get_doceria_db()
    data = request.get_json() or {}
    row = db.execute('SELECT * FROM configuracoes LIMIT 1').fetchone()
    if row:
        db.execute('''UPDATE configuracoes SET whatsapp=?, instagram=?, endereco=?, horario_funcionamento=? WHERE id=?''',
                   (data.get('whatsapp', ''), data.get('instagram', ''),
                    data.get('endereco', ''), data.get('horario_funcionamento', ''), row['id']))
    else:
        db.execute('''INSERT INTO configuracoes (whatsapp, instagram, endereco, horario_funcionamento) VALUES (?,?,?,?)''',
                   (data.get('whatsapp', ''), data.get('instagram', ''),
                    data.get('endereco', ''), data.get('horario_funcionamento', '')))
    db.commit()
    updated = db.execute('SELECT * FROM configuracoes LIMIT 1').fetchone()
    return jsonify(row_to_dict(updated))


@app.route('/api/stats', methods=['GET'])
@require_admin
def get_stats():
    db = get_doceria_db()
    total = db.execute('SELECT COUNT(*) as c FROM produtos').fetchone()['c']
    ativos = db.execute('SELECT COUNT(*) as c FROM produtos WHERE ativo=1').fetchone()['c']
    inativos = db.execute('SELECT COUNT(*) as c FROM produtos WHERE ativo=0').fetchone()['c']
    return jsonify({'total': total, 'ativos': ativos, 'inativos': inativos})


# ============================================================
# FORMULÁRIOS OSC - ADMIN
# ============================================================

def serialize_question(row):
    q = dict(row)
    q["required"] = bool(q["is_required"])
    q["allow_multiple_files"] = False
    q["min_files"] = 1
    q["max_files"] = 1
    q["use_as_folder_name"] = bool(q["use_for_folder_name"])
    q["options"] = json.loads(q["options"]) if q["options"] else []

    if q["file_config"]:
        cfg = json.loads(q["file_config"])
        q["allow_multiple_files"] = bool(cfg.get("allow_multiple_files", False))
        q["min_files"] = int(cfg.get("min_files", 1))
        q["max_files"] = int(cfg.get("max_files", 9999))
    return q


def serialize_form(row, include_questions=True):
    form = dict(row)
    form["status"] = "active" if form["is_active"] else "inactive"
    form["public_token"] = form["public_id"]
    if include_questions:
        questions = get_forms_db().execute(
            "SELECT * FROM questions WHERE form_id=? ORDER BY sort_order",
            (form["id"],)
        ).fetchall()
        form["questions"] = [serialize_question(x) for x in questions]
    return form


@app.route("/api/dashboard", methods=["GET"])
@require_global_admin_jwt
def forms_dashboard():
    db = get_forms_db()
    active = db.execute("SELECT * FROM forms WHERE is_active=1 LIMIT 1").fetchone()
    return jsonify({
        "total_forms": db.execute("SELECT COUNT(*) AS c FROM forms").fetchone()["c"],
        "total_responses": db.execute("SELECT COUNT(*) AS c FROM responses").fetchone()["c"],
        "active_form": serialize_form(active, False) if active else None,
    })


@app.route("/api/forms", methods=["GET"])
@require_global_admin_jwt
def get_forms():
    db = get_forms_db()
    rows = db.execute("""
        SELECT f.*,
               (SELECT COUNT(*) FROM responses r WHERE r.form_id=f.id) AS response_count
        FROM forms f
        ORDER BY f.created_at DESC
    """).fetchall()
    return jsonify([serialize_form(row) for row in rows])


@app.route("/api/forms/<int:form_id>", methods=["GET"])
@require_global_admin_jwt
def get_form(form_id):
    row = get_forms_db().execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    if not row:
        return jsonify({"error": "Formulário não encontrado"}), 404
    return jsonify(serialize_form(row))


def normalize_question_payload(q, idx):
    qtype = q.get("type", "short_text")
    if qtype == "text":
        qtype = "short_text"
    if qtype == "choice":
        qtype = "multiple_choice"
    if qtype == "file":
        qtype = "pdf_file"

    if qtype not in {"short_text", "long_text", "multiple_choice", "pdf_file", "text_block"}:
        raise ValueError(f"Tipo de pergunta inválido: {qtype}")

    title = str(q.get("title", q.get("question", ""))).strip()
    if not title:
        title = "Pergunta sem título"

    options = q.get("options", []) or []
    if qtype == "multiple_choice":
        options = [str(x).strip() for x in options if str(x).strip()]
        if not options:
            raise ValueError(f"A pergunta '{title}' precisa de opções.")

    multiple = bool(q.get("allow_multiple_files", q.get("allowMultipleFiles", False)))
    min_files = int(q.get("min_files", 1 if q.get("required") else 0))
    max_files = int(q.get("max_files", 9999 if multiple else 1))

    if qtype != "pdf_file":
        multiple = False
        min_files = 0
        max_files = 0

    if qtype == "pdf_file" and not multiple:
        max_files = 1
        min_files = 1 if q.get("required") else 0

    if qtype == "pdf_file" and multiple:
        max_files = max(1, max_files)
        min_files = max(0, min_files)

    return {
        "title": title,
        "description": str(q.get("description", "")).strip(),
        "type": qtype,
        "required": bool(q.get("required", q.get("is_required", False))),
        "options": options,
        "allow_multiple_files": multiple,
        "min_files": min_files,
        "max_files": max_files,
        "use_as_folder_name": bool(q.get("use_as_folder_name", q.get("use_for_folder_name", False))),
        "file_label": str(q.get("file_label", q.get("fileLabel", ""))).strip(),
        "sort_order": idx,
    }


def replace_questions(db, form_id, questions):
    db.execute("DELETE FROM questions WHERE form_id=?", (form_id,))
    folder_question_id = None

    for idx, qraw in enumerate(questions):
        q = normalize_question_payload(qraw, idx)
        use_folder = q["use_as_folder_name"] and q["type"] in {"short_text", "long_text", "multiple_choice"}

        cur = db.execute("""
            INSERT INTO questions
            (form_id, question, description, type, is_required,
             sort_order, options, file_config, use_for_folder_name, file_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            form_id, q["title"], q["description"], q["type"],
            1 if q["required"] else 0, idx,
            json.dumps(q["options"], ensure_ascii=False),
            json.dumps({
                "allow_multiple_files": q["allow_multiple_files"],
                "min_files": q["min_files"],
                "max_files": q["max_files"],
            }) if q["type"] == "pdf_file" else None,
            1 if use_folder else 0,
            q["file_label"] or None,
        ))

        if use_folder:
            folder_question_id = cur.lastrowid

    db.execute(
        "UPDATE questions SET use_for_folder_name=0 WHERE form_id=? AND id != COALESCE(?, -1)",
        (form_id, folder_question_id)
    )
    db.execute("UPDATE forms SET folder_name_question_id=? WHERE id=?", (folder_question_id, form_id))


@app.route("/api/forms", methods=["POST"])
@require_global_admin_jwt
def create_form():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify({"error": "Título é obrigatório"}), 400

    db = get_forms_db()
    public_id = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    cur = db.execute("""
        INSERT INTO forms (public_id, title, description, image_data, is_active)
        VALUES (?, ?, ?, ?, 0)
    """, (public_id, title, str(data.get("description", "")), data.get("image_data")))
    form_id = cur.lastrowid

    try:
        replace_questions(db, form_id, data.get("questions", []))
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 400

    return jsonify(serialize_form(
        db.execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    )), 201


@app.route("/api/forms/<int:form_id>", methods=["PUT"])
@require_global_admin_jwt
def update_form(form_id):
    db = get_forms_db()
    row = db.execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    if not row:
        return jsonify({"error": "Formulário não encontrado"}), 404

    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify({"error": "Título é obrigatório"}), 400

    try:
        db.execute("""
            UPDATE forms
            SET title=?, description=?, image_data=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (title, str(data.get("description", "")), data.get("image_data"), form_id))
        replace_questions(db, form_id, data.get("questions", []))
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 400

    return jsonify(serialize_form(
        db.execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    ))


@app.route("/api/forms/<int:form_id>", methods=["DELETE"])
@require_global_admin_jwt
def delete_form(form_id):
    db = get_forms_db()
    row = db.execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    if not row:
        return jsonify({"error": "Formulário não encontrado"}), 404

    count = db.execute(
        "SELECT COUNT(*) AS c FROM responses WHERE form_id=?", (form_id,)
    ).fetchone()["c"]
    if count:
        return jsonify({
            "error": "Este formulário possui respostas e não pode ser excluído. Desative-o."
        }), 409

    db.execute("DELETE FROM forms WHERE id=?", (form_id,))
    db.commit()
    return jsonify({"success": True})


@app.route("/api/forms/<int:form_id>/activate", methods=["POST"])
@require_global_admin_jwt
def activate_form(form_id):
    db = get_forms_db()
    row = db.execute("SELECT id FROM forms WHERE id=?", (form_id,)).fetchone()
    if not row:
        return jsonify({"error": "Formulário não encontrado"}), 404

    db.execute("BEGIN IMMEDIATE")
    db.execute("UPDATE forms SET is_active=0")
    db.execute("UPDATE forms SET is_active=1 WHERE id=?", (form_id,))
    db.commit()
    return jsonify({"success": True, "is_active": 1})


@app.route("/api/forms/<int:form_id>/deactivate", methods=["POST"])
@require_global_admin_jwt
def deactivate_form(form_id):
    db = get_forms_db()
    row = db.execute("SELECT id FROM forms WHERE id=?", (form_id,)).fetchone()
    if not row:
        return jsonify({"error": "Formulário não encontrado"}), 404
    db.execute("UPDATE forms SET is_active=0 WHERE id=?", (form_id,))
    db.commit()
    return jsonify({"success": True, "is_active": 0})


@app.route("/api/forms/<int:form_id>/duplicate", methods=["POST"])
@require_global_admin_jwt
def duplicate_form(form_id):
    db = get_forms_db()
    source = db.execute("SELECT * FROM forms WHERE id=?", (form_id,)).fetchone()
    if not source:
        return jsonify({"error": "Formulário não encontrado"}), 404

    new_id = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    cur = db.execute("""
        INSERT INTO forms (public_id, title, description, image_data, is_active)
        VALUES (?, ?, ?, ?, 0)
    """, (new_id, source["title"] + " (Cópia)", source["description"], source["image_data"]))
    new_form_id = cur.lastrowid

    questions = db.execute(
        "SELECT * FROM questions WHERE form_id=? ORDER BY sort_order", (form_id,)
    ).fetchall()

    for q in questions:
        db.execute("""
            INSERT INTO questions
            (form_id, question, description, type, is_required,
             sort_order, options, file_config, use_for_folder_name, file_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_form_id, q["question"], q["description"], q["type"],
            q["is_required"], q["sort_order"], q["options"],
            q["file_config"], q["use_for_folder_name"], q["file_label"]
        ))

    db.commit()
    return jsonify(serialize_form(
        db.execute("SELECT * FROM forms WHERE id=?", (new_form_id,)).fetchone()
    )), 201


# ============================================================
# FORMULÁRIOS OSC - PÚBLICO
# ============================================================

@app.route("/api/public/forms/<public_id>", methods=["GET"])
def get_public_form(public_id):
    db = get_forms_db()
    form = db.execute("SELECT * FROM forms WHERE public_id=?", (public_id,)).fetchone()

    if not form:
        return jsonify({"error": "Formulário não encontrado"}), 404
    if not form["is_active"]:
        return jsonify({"error": "Este formulário não está mais disponível."}), 410

    result = serialize_form(form)
    public_questions = []
    for q in result["questions"]:
        public_questions.append({
            "id": str(q["id"]),
            "title": q["question"],
            "description": q["description"],
            "type": q["type"],
            "required": q["required"],
            "options": q["options"],
            "allow_multiple_files": q["allow_multiple_files"],
            "min_files": q["min_files"],
            "max_files": q["max_files"],
            "file_label": q["file_label"],
        })

    return jsonify({
        "id": result["id"],
        "public_id": result["public_id"],
        "title": result["title"],
        "description": result["description"],
        "image_data": result.get("image_data"),
        "questions": public_questions,
    })


def extract_submitted_files(question_id):
    files = []
    prefix = f"file_{question_id}"
    for key in request.files.keys():
        if key == prefix or key.startswith(prefix + "_"):
            files.extend(request.files.getlist(key))
    return [f for f in files if f and f.filename]


def sanitize_name(value, fallback="Resposta"):
    value = str(value or "").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = value.replace("..", "_")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value[:180] or fallback)


def normalize_pdf_name(label, folder_name):
    label = sanitize_name(label, "Documento")
    folder = sanitize_name(folder_name, "Instituicao")
    return f"{label} - {folder}.pdf"


def validate_pdf(upload):
    if not upload or not upload.filename:
        return False, "Arquivo não informado."
    if not upload.filename.lower().endswith(".pdf"):
        return False, "Apenas arquivos PDF são permitidos."
    pos = upload.stream.tell()
    header = upload.stream.read(5)
    upload.stream.seek(pos)
    if header != b"%PDF-":
        return False, "O arquivo não possui uma assinatura PDF válida."
    return True, ""


def quote_path(value):
    from urllib.parse import quote
    return quote(value, safe="")


def get_graph_token():
    global _token_cache
    if _token_cache["access_token"] and _token_cache["expires_at"] > time.time() + 60:
        return _token_cache["access_token"]

    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    response = requests.post(
        token_url,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Falha ao obter token Graph: {response.text[:1000]}")

    data = response.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["access_token"]


def graph_request(method, endpoint, data=None, raw=None, headers=None, timeout=120):
    token = get_graph_token()
    url = "https://graph.microsoft.com/v1.0/" + endpoint.lstrip("/")
    hdr = {"Authorization": f"Bearer {token}"}
    if headers:
        hdr.update(headers)

    if raw is not None:
        response = requests.request(method, url, headers=hdr, data=raw, timeout=timeout)
    else:
        response = requests.request(method, url, headers=hdr, json=data, timeout=timeout)

    if response.status_code == 401:
        _token_cache["access_token"] = None
        token = get_graph_token()
        hdr["Authorization"] = f"Bearer {token}"
        if raw is not None:
            response = requests.request(method, url, headers=hdr, data=raw, timeout=timeout)
        else:
            response = requests.request(method, url, headers=hdr, json=data, timeout=timeout)
    return response


def create_sharepoint_folder(folder_name):
    safe = sanitize_name(folder_name)
    endpoint = f"sites/{SHAREPOINT_SITE_ID}/drives/{SHAREPOINT_DRIVE_ID}/root/children"
    response = graph_request("POST", endpoint, data={
        "name": safe,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "rename",
    })
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Erro ao criar pasta no SharePoint: {response.text[:1000]}")
    return response.json()


def upload_pdf_to_sharepoint(folder_id, stored_name, upload):
    stream = upload.stream
    stream.seek(0)
    size = upload.content_length

    if size is None:
        current = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(current)

    safe_name = sanitize_name(stored_name, "Documento.pdf")
    encoded = quote_path(safe_name)

    if size <= 4 * 1024 * 1024:
        endpoint = f"sites/{SHAREPOINT_SITE_ID}/drives/{SHAREPOINT_DRIVE_ID}/items/{folder_id}:/{encoded}:/content"
        data = stream.read()
        response = graph_request("PUT", endpoint, raw=data,
                                  headers={"Content-Type": "application/pdf"}, timeout=300)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Erro no upload PDF: {response.text[:1000]}")
        return response.json()

    endpoint = f"sites/{SHAREPOINT_SITE_ID}/drives/{SHAREPOINT_DRIVE_ID}/items/{folder_id}:/{encoded}:/createUploadSession"
    session_response = graph_request("POST", endpoint, data={
        "item": {"@microsoft.graph.conflictBehavior": "rename", "name": safe_name}
    })
    if session_response.status_code not in (200, 201):
        raise RuntimeError(f"Erro ao criar sessão de upload: {session_response.text[:1000]}")

    upload_url = session_response.json()["uploadUrl"]
    chunk_size = 5 * 1024 * 1024
    offset = 0

    while offset < size:
        chunk = stream.read(chunk_size)
        if not chunk:
            raise RuntimeError("Leitura incompleta do arquivo durante upload.")

        end = offset + len(chunk) - 1
        response = requests.put(
            upload_url,
            headers={
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{end}/{size}",
            },
            data=chunk,
            timeout=600,
        )
        if response.status_code not in (200, 201, 202):
            raise RuntimeError(f"Erro no upload em chunks: {response.text[:1000]}")
        offset = end + 1

    return response.json()


def delete_sharepoint_item(item_id):
    """Exclui um item (arquivo ou pasta) do SharePoint. 404 conta como
    sucesso (já não existe). Lança exceção para qualquer outro erro."""
    if not item_id:
        return True
    endpoint = f"sites/{SHAREPOINT_SITE_ID}/drives/{SHAREPOINT_DRIVE_ID}/items/{item_id}"
    response = graph_request("DELETE", endpoint)
    if response.status_code in (204, 404):
        return True
    raise RuntimeError(f"Falha ao excluir item do SharePoint: {response.text[:500]}")


@app.route("/api/public/forms/<public_id>/submit", methods=["POST"])
def submit_public_form(public_id):
    db = get_forms_db()
    form = db.execute("SELECT * FROM forms WHERE public_id=?", (public_id,)).fetchone()

    if not form:
        return jsonify({"error": "Formulário não encontrado"}), 404
    if not form["is_active"]:
        return jsonify({"error": "Este formulário não está mais disponível."}), 410

    questions = db.execute(
        "SELECT * FROM questions WHERE form_id=? ORDER BY sort_order", (form["id"],)
    ).fetchall()

    try:
        answers_payload = json.loads(request.form.get("answers", "{}"))
    except json.JSONDecodeError:
        answers_payload = {}

    errors = []
    prepared_files = {}

    for qrow in questions:
        q = serialize_question(qrow)
        qid = str(q["id"])

        if q["type"] == "text_block":
            continue

        if q["type"] == "pdf_file":
            files = extract_submitted_files(q["id"])
            prepared_files[qid] = files

            if q["required"] and len(files) < max(1, q["min_files"]):
                errors.append(f"'{q['question']}' exige pelo menos {max(1, q['min_files'])} PDF(s).")

            if len(files) > q["max_files"]:
                errors.append(f"'{q['question']}' permite no máximo {q['max_files']} PDF(s).")

            for upload in files:
                ok, reason = validate_pdf(upload)
                if not ok:
                    errors.append(f"{q['question']}: {upload.filename}: {reason}")
        else:
            value = str(answers_payload.get(qid, "") or "").strip()
            if q["required"] and not value:
                errors.append(f"'{q['question']}' é obrigatório.")
            if q["type"] == "multiple_choice" and value and value not in q["options"]:
                errors.append(f"Resposta inválida para '{q['question']}'.")

    if errors:
        return jsonify({
            "error": "Corrija os campos indicados antes de enviar.",
            "details": errors,
            "draft_should_be_kept": True,
        }), 400

    folder_question = db.execute("""
        SELECT * FROM questions WHERE form_id=? AND use_for_folder_name=1 LIMIT 1
    """, (form["id"],)).fetchone()

    if folder_question:
        folder_name = str(answers_payload.get(str(folder_question["id"]), "") or "").strip()
    else:
        folder_name = ""

    if not folder_name:
        folder_name = f"Resposta-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    folder_name = sanitize_name(folder_name)

    created_item_ids = []
    try:
        folder = create_sharepoint_folder(folder_name)
        folder_id = folder["id"]

        uploaded_records = []

        for qrow in questions:
            q = serialize_question(qrow)
            if q["type"] != "pdf_file":
                continue

            files = prepared_files.get(str(q["id"]), [])
            for upload in files:
                stored_name = normalize_pdf_name(q["file_label"] or q["question"], folder_name)

                existing_names = {x["stored_name"] for x in uploaded_records}
                if stored_name in existing_names:
                    stem = stored_name[:-4]
                    stored_name = f"{stem} ({len(existing_names)+1}).pdf"

                result = upload_pdf_to_sharepoint(folder_id, stored_name, upload)
                item_id = result["id"]
                created_item_ids.append(item_id)

                uploaded_records.append({
                    "question_id": q["id"],
                    "original_name": upload.filename,
                    "stored_name": result.get("name", stored_name),
                    "sharepoint_item_id": item_id,
                    "sharepoint_folder_id": folder_id,
                    "web_url": result.get("webUrl"),
                    "file_size": int(result.get("size", upload.content_length or 0)),
                })

        db.execute("BEGIN IMMEDIATE")
        cur = db.execute("""
            INSERT INTO responses (form_id, folder_name, folder_id) VALUES (?, ?, ?)
        """, (form["id"], folder_name, folder_id))
        response_id = cur.lastrowid

        for qrow in questions:
            q = serialize_question(qrow)
            if q["type"] in ("text_block", "pdf_file"):
                continue
            value = str(answers_payload.get(str(q["id"]), "") or "").strip()
            db.execute("""
                INSERT INTO answers (response_id, question_id, answer) VALUES (?, ?, ?)
            """, (response_id, q["id"], value))

        for item in uploaded_records:
            db.execute("""
                INSERT INTO files
                (response_id, question_id, original_name, stored_name,
                 sharepoint_item_id, sharepoint_folder_id, web_url, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                response_id, item["question_id"], item["original_name"], item["stored_name"],
                item["sharepoint_item_id"], item["sharepoint_folder_id"],
                item["web_url"], item["file_size"],
            ))

        db.commit()

        return jsonify({
            "success": True,
            "message": "Formulário enviado com sucesso!",
            "response_id": response_id,
            "uploaded": uploaded_records,
        }), 201

    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        for item_id in reversed(created_item_ids):
            try:
                delete_sharepoint_item(item_id)
            except Exception:
                pass

        return jsonify({
            "error": (
                "Não foi possível concluir o envio dos documentos. "
                "Nenhuma resposta foi finalizada. Seus dados continuam "
                "no rascunho do navegador para você tentar novamente."
            ),
            "details": [str(exc)],
            "draft_should_be_kept": True,
        }), 502


# ============================================================
# FORMULÁRIOS OSC - RESPOSTAS / DOWNLOADS
# ============================================================

@app.route("/api/responses", methods=["GET"])
@require_global_admin_jwt
def get_responses():
    db = get_forms_db()
    form_id = request.args.get("form_id")

    if form_id:
        rows = db.execute("""
            SELECT r.*, f.title AS form_title
            FROM responses r INNER JOIN forms f ON f.id=r.form_id
            WHERE r.form_id=?
            ORDER BY r.submitted_at DESC
        """, (form_id,)).fetchall()
    else:
        rows = db.execute("""
            SELECT r.*, f.title AS form_title
            FROM responses r INNER JOIN forms f ON f.id=r.form_id
            ORDER BY r.submitted_at DESC
        """).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["created_at"] = item["submitted_at"]
        item["files_count"] = db.execute(
            "SELECT COUNT(*) AS c FROM files WHERE response_id=?", (row["id"],)
        ).fetchone()["c"]
        result.append(item)
    return jsonify(result)


@app.route("/api/responses/<int:response_id>", methods=["GET", "DELETE"])
@require_global_admin_jwt
def response_detail(response_id):
    db = get_forms_db()

    response = db.execute("""
        SELECT r.*, f.title AS form_title
        FROM responses r INNER JOIN forms f ON f.id=r.form_id
        WHERE r.id=?
    """, (response_id,)).fetchone()

    if not response:
        return jsonify({"error": "Resposta não encontrada"}), 404

    if request.method == "DELETE":
        files = db.execute(
            "SELECT * FROM files WHERE response_id=?", (response_id,)
        ).fetchall()

        try:
            for file_row in files:
                delete_sharepoint_item(file_row["sharepoint_item_id"])
            try:
                delete_sharepoint_item(response["folder_id"])
            except Exception:
                pass
        except Exception as exc:
            return jsonify({
                "error": "Não foi possível excluir os arquivos no SharePoint. A resposta não foi removida.",
                "details": [str(exc)],
            }), 502

        db.execute("DELETE FROM responses WHERE id=?", (response_id,))
        db.commit()
        return jsonify({"success": True})

    answers = db.execute("""
        SELECT a.*, q.question, q.type
        FROM answers a INNER JOIN questions q ON q.id=a.question_id
        WHERE a.response_id=?
        ORDER BY q.sort_order
    """, (response_id,)).fetchall()

    files = db.execute("""
        SELECT f.*, q.question, q.file_label
        FROM files f INNER JOIN questions q ON q.id=f.question_id
        WHERE f.response_id=?
        ORDER BY f.id
    """, (response_id,)).fetchall()

    return jsonify({
        "form_title": response["form_title"],
        "response": dict(response),
        "answers": [dict(x) for x in answers],
        "files": [dict(x) for x in files],
    })


@app.route("/api/files/<int:file_id>/download", methods=["GET"])
@require_global_admin_jwt
def download_file(file_id):
    db = get_forms_db()
    file = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    if not file:
        return jsonify({"error": "Arquivo não encontrado"}), 404

    endpoint = f"sites/{SHAREPOINT_SITE_ID}/drives/{SHAREPOINT_DRIVE_ID}/items/{file['sharepoint_item_id']}/content"
    response = graph_request("GET", endpoint, timeout=300)
    if response.status_code != 200:
        return jsonify({"error": f"Erro ao baixar PDF do SharePoint: {response.text[:500]}"}), 502

    result = make_response(response.content)
    result.headers["Content-Type"] = "application/pdf"
    result.headers["Content-Disposition"] = f'attachment; filename="{secure_filename(file["stored_name"])}"'
    return result


@app.route("/api/responses/<int:response_id>/files/<int:file_id>/download", methods=["GET"])
@require_global_admin_jwt
def download_file_compat(response_id, file_id):
    row = get_forms_db().execute("SELECT response_id FROM files WHERE id=?", (file_id,)).fetchone()
    if not row or int(row["response_id"]) != int(response_id):
        return jsonify({"error": "Arquivo não encontrado"}), 404
    return download_file(file_id)


# ============================================================
# ARQUIVOS ESTÁTICOS / HTML
# ============================================================

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/admin')
def admin():
    return send_from_directory('.', 'admin.html')


@app.route('/formsadmin')
@app.route('/formsadmin.html')
def forms_admin_page():
    return send_from_directory('.', 'formsdamin.html')


@app.route('/form/<public_id>')
def public_form_page(public_id):
    return send_from_directory('.', 'forms.html')


@app.route('/<path:filename>')
def serve_static(filename):
    if os.path.exists(filename):
        return send_from_directory('.', filename)
    return 'Not found', 404


# ============================================================
# INIT
# ============================================================

os.makedirs('uploads', exist_ok=True)
init_doceria_db()
init_forms_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5006)