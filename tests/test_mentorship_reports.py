import ast
import os
import re
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    HRFlowable, KeepTogether, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from xml.sax.saxutils import escape


API_PATH = Path(__file__).resolve().parents[1] / '.env' / 'api.py'
REPORT_NODES = {
    'NumberedCanvas',
    'REPORT_COLORS',
    'KPI_GREEN',
    'KPI_BLUE',
    'KPI_AMBER',
    'KPI_PURPLE',
    'CONTENT_WIDTH',
    '_build_report_styles',
    '_canvas_with_title',
    '_load_report_logo',
    '_build_report_header',
    '_build_kpi_table',
    '_extrair_nota_mentoria',
    '_agregar_desempenho_mentoria',
    'gerar_pdf_mentoria',
}


def carregar_funcoes_relatorio():
    namespace = {
        're': re,
        'os': os,
        'datetime': datetime,
        'BASE_DIR': str(API_PATH.parents[1]),
        'svg2rlg': None,
        'sanitizar_texto': lambda value: value,
        'pdfcanvas': pdfcanvas,
        'BytesIO': BytesIO,
        'SimpleDocTemplate': SimpleDocTemplate,
        'A4': A4,
        'mm': mm,
        'getSampleStyleSheet': getSampleStyleSheet,
        'ParagraphStyle': ParagraphStyle,
        'colors': colors,
        'TA_CENTER': TA_CENTER,
        'TA_LEFT': TA_LEFT,
        'Paragraph': Paragraph,
        'escape': escape,
        'Table': Table,
        'TableStyle': TableStyle,
        'Spacer': Spacer,
        'HRFlowable': HRFlowable,
        'KeepTogether': KeepTogether,
        'Drawing': Drawing,
        'HorizontalBarChart': HorizontalBarChart,
    }
    tree = ast.parse(API_PATH.read_text(encoding='utf-8'))
    for node in tree.body:
        node_name = (
            node.name if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            else node.targets[0].id if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            else None
        )
        if node_name in REPORT_NODES:
            exec(
                compile(ast.Module(body=[node], type_ignores=[]), str(API_PATH), 'exec'),
                namespace
            )
    return namespace


class MentorshipReportTests(unittest.TestCase):
    def test_scores_are_aggregated_per_class_cycle_and_question(self):
        functions = carregar_funcoes_relatorio()
        respostas = [
            {
                'aluno_id': 1, 'turma_id': 10, 'turma_nome': 'Turma A',
                'ciclo_id': 100, 'ciclo_nome': 'Ciclo 01', 'pergunta_id': 1,
                'pergunta': 'Desempenho geral', 'tipo': 'multiple',
                'resposta': '8 - Bom',
            },
            {
                'aluno_id': 1, 'turma_id': 10, 'turma_nome': 'Turma A',
                'ciclo_id': 100, 'ciclo_nome': 'Ciclo 01', 'pergunta_id': 1,
                'pergunta': 'Desempenho geral', 'tipo': 'multiple',
                'resposta': '8 - Bom',
            },
            {
                'aluno_id': 2, 'turma_id': 10, 'turma_nome': 'Turma A',
                'ciclo_id': 100, 'ciclo_nome': 'Ciclo 01', 'pergunta_id': 1,
                'pergunta': 'Desempenho geral', 'tipo': 'multiple',
                'resposta': '10 - Excelente',
            },
            {
                'aluno_id': 1, 'turma_id': 10, 'turma_nome': 'Turma A',
                'ciclo_id': 100, 'ciclo_nome': 'Ciclo 01', 'pergunta_id': 2,
                'pergunta': 'Comentário', 'tipo': 'text', 'resposta': 'Muito bem',
            },
            {
                'aluno_id': 3, 'turma_id': 20, 'turma_nome': 'Turma B',
                'ciclo_id': 100, 'ciclo_nome': 'Ciclo 01', 'pergunta_id': 1,
                'pergunta': 'Desempenho geral', 'tipo': 'multiple',
                'resposta': '6 - Regular',
            },
        ]

        metricas = functions['_agregar_desempenho_mentoria'](
            respostas,
            {1: {'min': 1, 'max': 10}},
        )

        turma_a = metricas[(10, 100, 1)]
        self.assertEqual(turma_a['quantidade'], 2)
        self.assertEqual(turma_a['media'], 9)
        self.assertEqual(turma_a['escala_min'], 1)
        self.assertEqual(turma_a['escala_max'], 10)
        self.assertIn((20, 100, 1), metricas)
        self.assertNotIn((10, 100, 2), metricas)
        self.assertEqual(functions['_extrair_nota_mentoria']('5 - Excelente'), 5)
        self.assertIsNone(functions['_extrair_nota_mentoria']('Muito bom'))

    def test_report_pdf_renders_aggregate_chart_without_raw_answers(self):
        functions = carregar_funcoes_relatorio()
        pdf = functions['gerar_pdf_mentoria'](
            'Visão Geral da Mentoria',
            'Gerado para conferência',
            [{
                'titulo': 'Desempenho — Turma A — Ciclo 01',
                'texto': '2 alunos responderam',
                'linhas': [
                    ['Pergunta', 'Média', 'Avaliações', 'Escala'],
                    ['Desempenho geral', '9.00', '2', '1–10'],
                ],
                'larguras': [101 * mm, 23 * mm, 25 * mm, 25 * mm],
                'grafico': {
                    'rotulos': ['Desempenho geral'],
                    'valores': [9],
                    'escala_max': 10,
                },
            }],
            solicitante='admin-teste',
            kpis=[
                ('TURMAS', 1, functions['KPI_GREEN']),
                ('ALUNOS', 2, functions['KPI_BLUE']),
            ],
        )

        content = pdf.getvalue()
        self.assertTrue(content.startswith(b'%PDF-'))
        self.assertGreater(len(content), 1000)


if __name__ == '__main__':
    unittest.main()
