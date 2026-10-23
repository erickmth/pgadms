import ast
import contextlib
import io
import secrets
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


API_PATH = Path(__file__).resolve().parents[1] / '.env' / 'api.py'
MENTORSHIP_FUNCTIONS = {
    'init_mentorship_db',
    'get_active_cycle_by_link',
    'aluno_vinculado_ao_mentor',
}


def criar_runtime(db_path):
    namespace = {
        'datetime': datetime,
        'secrets': secrets,
    }

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    namespace['get_db'] = get_db
    namespace['execute_with_retry'] = lambda func: func()
    tree = ast.parse(API_PATH.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in MENTORSHIP_FUNCTIONS:
            exec(
                compile(ast.Module(body=[node], type_ignores=[]), str(API_PATH), 'exec'),
                namespace
            )
    return namespace, get_db


class MentorshipCycleLinkTests(unittest.TestCase):
    def test_legacy_cycles_receive_unique_tokens_and_only_active_cycle_opens(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, get_db = criar_runtime(Path(temp) / 'mentoria.sqlite3')
            conn = get_db()
            conn.execute('''
                CREATE TABLE mentoria_ciclos (
                    id INTEGER PRIMARY KEY,
                    nome TEXT NOT NULL,
                    form_id INTEGER,
                    data_inicio TIMESTAMP NOT NULL,
                    data_fim TIMESTAMP NOT NULL,
                    ativo INTEGER DEFAULT 0,
                    deleted_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT
                )
            ''')
            conn.executemany('''
                INSERT INTO mentoria_ciclos (nome, data_inicio, data_fim, ativo)
                VALUES (?, ?, ?, ?)
            ''', [
                ('Ciclo ativo', '2020-01-01 00:00:00', '2035-01-01 00:00:00', 1),
                ('Ciclo inativo', '2020-01-01 00:00:00', '2035-01-01 00:00:00', 0),
            ])
            conn.commit()
            conn.close()

            with contextlib.redirect_stdout(io.StringIO()):
                namespace['init_mentorship_db']()

            conn = get_db()
            tokens = [
                row['link_token'] for row in conn.execute(
                    'SELECT link_token FROM mentoria_ciclos ORDER BY id'
                )
            ]
            self.assertTrue(all(tokens))
            self.assertEqual(len(set(tokens)), 2)

            now = datetime.now()
            conn.execute('INSERT INTO mentoria_formularios (titulo) VALUES (?)', ('Formulário',))
            conn.execute('''
                UPDATE mentoria_ciclos
                SET form_id = 1, data_inicio = ?, data_fim = ?
                WHERE id = 1
            ''', (
                (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
                (now + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
            ))
            conn.commit()
            conn.close()

            self.assertEqual(namespace['get_active_cycle_by_link'](tokens[0])['id'], 1)
            self.assertIsNone(namespace['get_active_cycle_by_link'](tokens[1]))
            self.assertIsNone(namespace['get_active_cycle_by_link']('invalid-link'))

    def test_mentor_can_only_access_linked_students(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, get_db = criar_runtime(Path(temp) / 'mentoria.sqlite3')
            with contextlib.redirect_stdout(io.StringIO()):
                namespace['init_mentorship_db']()

            conn = get_db()
            conn.execute('INSERT INTO mentoria_turmas (nome) VALUES (?)', ('Turma',))
            conn.execute(
                'INSERT INTO mentoria_alunos (nome, turma_id) VALUES (?, 1)',
                ('Aluno vinculado',)
            )
            conn.execute(
                'INSERT INTO mentoria_mentores (nome, edv, senha_hash) VALUES (?, ?, ?)',
                ('Mentor', 'edv-1', 'hash')
            )
            conn.execute(
                'INSERT INTO mentoria_relacao (aluno_id, mentor_id) VALUES (1, 1)'
            )
            conn.commit()
            conn.close()

            self.assertTrue(namespace['aluno_vinculado_ao_mentor'](1, 1))
            self.assertFalse(namespace['aluno_vinculado_ao_mentor'](1, 2))


if __name__ == '__main__':
    unittest.main()
