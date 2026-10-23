import ast
import json
import random
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


API_PATH = Path(__file__).resolve().parents[1] / '.env' / 'api.py'
SCALE_FUNCTIONS = {
    '_chave_dupla',
    '_pontuar_distribuicao',
    'gerar_duplas_diversas',
    'obter_historico_duplas',
    'obter_ultima_data_escala',
    'obter_proximo_dia_util',
    'validar_duplas',
    'validar_duplas_manuais',
    'normalizar_dupla_manual',
    'gerar_escala_fair',
    'verificar_e_gerar_nova_escala',
    '_detalhes_distribuicao',
    '_identidade_auditoria',
    '_inserir_auditoria_escala',
    'salvar_escala',
}


def criar_runtime(db_path):
    # Load only the scale functions so tests do not initialize the Flask application.
    namespace = {
        'datetime': datetime,
        'json': json,
        'random': random,
        'sqlite3': sqlite3,
        'timedelta': timedelta,
        'timezone': timezone,
        'DATA_INICIO_ESCALA': datetime(2026, 4, 6),
        'DATA_LIMITE_AUTOMATICA': datetime.now() + timedelta(days=365),
        'sanitizar_texto': lambda text: text,
        'get_admin_by_username': lambda username: None,
        'log_admin_action': lambda *args: None,
    }

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    namespace['get_db'] = get_db
    tree = ast.parse(API_PATH.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in SCALE_FUNCTIONS:
            exec(
                compile(ast.Module(body=[node], type_ignores=[]), str(API_PATH), 'exec'),
                namespace
            )
    return namespace, get_db


def criar_banco_teste(get_db):
    conn = get_db()
    conn.executescript('''
        CREATE TABLE turmas(id INTEGER PRIMARY KEY, nome TEXT);
        CREATE TABLE alunos(
            id INTEGER PRIMARY KEY,
            nome TEXT,
            turma_id INTEGER,
            is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE escalas(
            id INTEGER PRIMARY KEY,
            turma_id INTEGER,
            semana_numero INTEGER,
            data_inicio TEXT,
            data_fim TEXT,
            dupla TEXT
        );
        CREATE TABLE escalas_historico(
            id INTEGER PRIMARY KEY,
            turma_id INTEGER,
            gerado_em TEXT DEFAULT CURRENT_TIMESTAMP,
            dados TEXT
        );
        CREATE TABLE historico_alteracoes_escalas(
            id INTEGER PRIMARY KEY,
            administrador_id INTEGER,
            nome_administrador TEXT,
            turma_id INTEGER,
            nome_turma TEXT,
            tipo_acao TEXT,
            data_hora TEXT,
            status TEXT,
            detalhes TEXT
        );
        CREATE TABLE auto_generation_log(
            id INTEGER PRIMARY KEY,
            turma_id INTEGER,
            semanas_geradas INTEGER,
            status TEXT
        );
        INSERT INTO turmas(id, nome) VALUES (1, 'Turma alvo'), (2, 'Outra turma');
    ''')
    conn.commit()
    conn.close()


class ScaleDistributionTests(unittest.TestCase):
    def test_even_rosters_generate_dynamic_number_of_weeks(self):
        for participant_count in (2, 10, 18, 24, 100):
            with self.subTest(participant_count=participant_count):
                with tempfile.TemporaryDirectory() as temp:
                    db_path = Path(temp) / 'scales.sqlite3'
                    namespace, get_db = criar_runtime(db_path)
                    criar_banco_teste(get_db)
                    participants = [f'Aluno {i:02d}' for i in range(participant_count)]
                    conn = get_db()
                    conn.executemany(
                        'INSERT INTO alunos(nome, turma_id, is_admin) VALUES (?, 1, 0)',
                        [(name,) for name in participants]
                    )
                    conn.execute(
                        'INSERT INTO alunos(nome, turma_id, is_admin) VALUES (?, 1, 1)',
                        ('Administrador',)
                    )
                    conn.commit()
                    conn.close()

                    random.seed(42)
                    start = datetime(2026, 8, 3)
                    weeks = namespace['gerar_escala_fair'](
                        'Turma alvo',
                        data_inicio=start
                    )
                    pairs = [week['dupla'] for week in weeks]

                    self.assertEqual(len(weeks), participant_count // 2)
                    self.assertTrue(namespace['validar_duplas'](participants, pairs))
                    for index, week in enumerate(weeks):
                        week_start = start + timedelta(weeks=index)
                        self.assertEqual(
                            week['data_inicio'],
                            week_start.strftime('%Y-%m-%d')
                        )
                        self.assertEqual(
                            week['data_fim'],
                            (week_start + timedelta(days=4)).strftime('%Y-%m-%d')
                        )

    def test_odd_roster_repeats_first_participant_in_an_additional_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, get_db = criar_runtime(Path(temp) / 'scales.sqlite3')
            criar_banco_teste(get_db)
            participants = [f'Aluno {i}' for i in range(15)]
            conn = get_db()
            conn.executemany(
                'INSERT INTO alunos(nome, turma_id, is_admin) VALUES (?, 1, 0)',
                [(name,) for name in participants]
            )
            conn.commit()
            conn.close()

            random.seed(42)
            weeks = namespace['gerar_escala_fair']('Turma alvo')
            pairs = [week['dupla'] for week in weeks]
            occurrences = {
                name: sum(pair.count(name) for pair in pairs)
                for name in participants
            }

            self.assertEqual(len(weeks), 8)
            self.assertTrue(namespace['validar_duplas'](participants, pairs))
            self.assertEqual(occurrences[participants[0]], 2)
            self.assertTrue(all(occurrences[name] == 1 for name in participants[1:]))
            self.assertTrue(all(pair[0] != pair[1] for pair in pairs))

            self.assertTrue(namespace['salvar_escala'](
                'Turma alvo',
                weeks,
                tipo_acao='geracao_automatica',
                administrador='Sistema (automático)'
            ))

    def test_manual_save_accepts_names_outside_student_roster(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, _ = criar_runtime(Path(temp) / 'scales.sqlite3')
            arbitrary_names = [
                ['Pessoa convidada', 'Nome que não está cadastrado'],
                ['Emanuelli Sophia', 'Lourenço']
            ]

            self.assertTrue(namespace['validar_duplas_manuais'](arbitrary_names))
            self.assertEqual(
                namespace['normalizar_dupla_manual'](
                    ['Ana e Silva', 'Maria e Souza']
                ),
                ['Ana e Silva', 'Maria e Souza']
            )
            self.assertFalse(namespace['validar_duplas_manuais']([['Ana', '']]))
            self.assertFalse(namespace['validar_duplas_manuais']([['Ana']]))

    def test_history_is_limited_to_its_class_and_avoids_old_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, get_db = criar_runtime(Path(temp) / 'scales.sqlite3')
            criar_banco_teste(get_db)
            participants = [f'Aluno {i:02d}' for i in range(12)]
            old_pairs = [
                participants[index:index + 2]
                for index in range(0, len(participants), 2)
            ]
            conn = get_db()
            conn.executemany(
                'INSERT INTO alunos(nome, turma_id, is_admin) VALUES (?, 1, 0)',
                [(name,) for name in participants]
            )
            conn.execute(
                'INSERT INTO escalas_historico(turma_id, dados) VALUES (2, ?)',
                (json.dumps([{'dupla': pair} for pair in old_pairs]),)
            )
            self.assertEqual(namespace['obter_historico_duplas'](1), [])
            conn.execute(
                'INSERT INTO escalas_historico(turma_id, dados) VALUES (1, ?)',
                (json.dumps([{'dupla': pair} for pair in old_pairs]),)
            )
            conn.commit()
            conn.close()

            random.seed(42)
            weeks = namespace['gerar_escala_fair']('Turma alvo')
            old_set = {tuple(sorted(pair)) for pair in old_pairs}
            self.assertTrue(all(tuple(sorted(week['dupla'])) not in old_set for week in weeks))

    def test_failed_persistence_keeps_current_scale_and_history(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, get_db = criar_runtime(Path(temp) / 'scales.sqlite3')
            criar_banco_teste(get_db)
            participants = [f'Aluno {i:02d}' for i in range(10)]
            conn = get_db()
            conn.executemany(
                'INSERT INTO alunos(nome, turma_id, is_admin) VALUES (?, 1, 0)',
                [(name,) for name in participants]
            )
            conn.commit()
            conn.close()

            weeks = namespace['gerar_escala_fair']('Turma alvo')
            self.assertTrue(namespace['salvar_escala'](
                'Turma alvo',
                weeks,
                tipo_acao='geracao_automatica',
                administrador='Sistema (automático)'
            ))
            conn = get_db()
            before = [
                tuple(row) for row in conn.execute(
                    'SELECT semana_numero, dupla FROM escalas WHERE turma_id = 1 ORDER BY semana_numero'
                )
            ]
            history_count = conn.execute(
                'SELECT COUNT(*) FROM escalas_historico WHERE turma_id = 1'
            ).fetchone()[0]
            audit_count = conn.execute(
                'SELECT COUNT(*) FROM historico_alteracoes_escalas WHERE turma_id = 1'
            ).fetchone()[0]
            auto_log_count = conn.execute(
                'SELECT COUNT(*) FROM auto_generation_log WHERE turma_id = 1'
            ).fetchone()[0]
            conn.execute('''
                CREATE TRIGGER fail_scale_insert
                BEFORE INSERT ON escalas
                BEGIN
                    SELECT RAISE(ABORT, 'injected failure');
                END
            ''')
            conn.commit()
            conn.close()

            with self.assertRaises(sqlite3.IntegrityError):
                namespace['salvar_escala'](
                    'Turma alvo',
                    weeks,
                    tipo_acao='geracao_automatica',
                    administrador='Sistema (automático)'
                )

            conn = get_db()
            after = [
                tuple(row) for row in conn.execute(
                    'SELECT semana_numero, dupla FROM escalas WHERE turma_id = 1 ORDER BY semana_numero'
                )
            ]
            self.assertEqual(after, before)
            self.assertEqual(
                conn.execute(
                    'SELECT COUNT(*) FROM escalas_historico WHERE turma_id = 1'
                ).fetchone()[0],
                history_count
            )
            self.assertEqual(
                conn.execute(
                    'SELECT COUNT(*) FROM historico_alteracoes_escalas WHERE turma_id = 1'
                ).fetchone()[0],
                audit_count
            )
            self.assertEqual(
                conn.execute(
                    'SELECT COUNT(*) FROM auto_generation_log WHERE turma_id = 1'
                ).fetchone()[0],
                auto_log_count
            )
            conn.close()

    def test_automatic_generation_uses_dynamic_roster_and_next_workday(self):
        with tempfile.TemporaryDirectory() as temp:
            namespace, get_db = criar_runtime(Path(temp) / 'scales.sqlite3')
            criar_banco_teste(get_db)
            participants = [f'Aluno {i:02d}' for i in range(20)]
            today = datetime.now().date()
            previous_end = today - timedelta(days=1)
            expected_start = previous_end + timedelta(days=1)
            while expected_start.weekday() >= 5:
                expected_start += timedelta(days=1)

            conn = get_db()
            conn.executemany(
                'INSERT INTO alunos(nome, turma_id, is_admin) VALUES (?, 1, 0)',
                [(name,) for name in participants]
            )
            conn.execute('''
                INSERT INTO escalas(turma_id, semana_numero, data_inicio, data_fim, dupla)
                VALUES (1, 1, ?, ?, ?)
            ''', (
                previous_end.strftime('%Y-%m-%d'),
                previous_end.strftime('%Y-%m-%d'),
                json.dumps(participants[:2])
            ))
            conn.commit()
            conn.close()

            generated, _ = namespace['verificar_e_gerar_nova_escala']()
            self.assertTrue(generated)
            conn = get_db()
            rows = conn.execute(
                'SELECT semana_numero, data_inicio, data_fim, dupla FROM escalas '
                'WHERE turma_id = 1 ORDER BY semana_numero'
            ).fetchall()
            pairs = [json.loads(row['dupla']) for row in rows]
            self.assertEqual(len(rows), 10)
            self.assertTrue(namespace['validar_duplas'](participants, pairs))
            self.assertEqual(rows[0]['data_inicio'], expected_start.strftime('%Y-%m-%d'))
            self.assertEqual(
                rows[-1]['data_fim'],
                (expected_start + timedelta(weeks=9, days=4)).strftime('%Y-%m-%d')
            )
            self.assertEqual(
                conn.execute(
                    'SELECT semanas_geradas FROM auto_generation_log WHERE turma_id = 1'
                ).fetchone()[0],
                10
            )
            conn.close()


if __name__ == '__main__':
    unittest.main()
