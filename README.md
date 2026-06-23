
# PGAdms – Sistema de Gestão para Programas Sociais

[![Status](https://img.shields.io/badge/status-em%20desenvolvimento-blue)](https://github.com/erickmth/pgadms)
[![Licença](https://img.shields.io/badge/licença-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/flask-3.1.0-black)](https://flask.palletsprojects.com)
[![Deploy na Vercel](https://img.shields.io/badge/deploy-vercel-black)](https://pgadms.vercel.app)
[![API Online](https://img.shields.io/badge/api-online-green)](https://erickmth.pythonanywhere.com)
[![Último Commit](https://img.shields.io/github/last-commit/erickmth/pgadms)](https://github.com/erickmth/pgadms)
[![Issues Abertas](https://img.shields.io/github/issues/erickmth/pgadms)](https://github.com/erickmth/pgadms/issues)

Sistema de gestão educacional que desenvolvo e mantenho como voluntário no **Instituto Robert Bosch (INRB)**, atendendo programas sociais como o **Formare 2026**. A plataforma gerencia **10 turmas** distribuídas em três regiões do Sul do Brasil (Curitiba, Joinville e Pomerode), centralizando operações que antes eram feitas manualmente.

## 📋 O que o sistema gerencia

| Módulo | Funcionalidades |
|--------|-----------------|
| **Presença** | Registro diário com suporte offline e sincronização automática. Cada turma tem seu dia de aula configurado (segunda, terça, quarta, quinta, sábado, dias úteis), com bloqueio inteligente de datas inválidas. Gera relatórios mensais em Excel com gráficos e contadores automáticos. |
| **Alunos e Turmas** | Cadastro individual, importação em lote via CSV/Excel, busca global por nome ou EDV em todas as turmas e vinculação de administradores. |
| **Escalas** | Sistema para criar e editar escalas de atividades (como limpeza), com geração automática baseada em data de início. |
| **Avisos** | Comunicados institucionais com suporte a Markdown, imagens, contagem regressiva e redirecionamento. |
| **Mentoria Socioemocional** | Módulo completo para avaliação de alunos por ciclos, com formulários personalizáveis, gráficos de evolução por competência e média geral de desenvolvimento. |
| **Super Admin** | Autenticação em dois fatores (2FA), gerenciamento de administradores com três níveis de permissão (Global, Formare, Turma), bloqueio de IPs, logs detalhados, modo manutenção e backup/restauração completa dos dados. |

## 🛠️ Tecnologias Utilizadas

**Frontend:** HTML5, CSS3, JavaScript (ES6+), Bootstrap 5, Chart.js, SheetJS (XLSX), Service Worker, Wake Lock API

**Backend:** Python 3.11+, Flask, SQLite, JWT, Flask-CORS, Flask-Limiter, OpenPyXL, Pillow, Bleach

**Infraestrutura:** PythonAnywhere (API), Vercel (Frontend), Git & GitHub

## 🚀 Como Executar Localmente

### Backend
```bash
# Clone o repositório
git clone https://github.com/erickmth/pgadms.git
cd pgadms

# Crie e ative um ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Instale as dependências
pip install -r requirements.txt

# Execute o servidor
python api.py
```

A API estará disponível em `http://localhost:5002`

### Frontend
Abra `index.html` diretamente no navegador ou use um servidor local:
```bash
python -m http.server 8000
```

## 🔐 Sistema de Permissões (RBAC)

| Tipo | Permissões |
|------|------------|
| **Global** | Acesso total a todos os módulos e turmas |
| **Formare** | Acesso à turma Formare, visualização de todas as turmas, upload, avisos, backup, escalas, alunos, histórico e relatórios |
| **Turma** | Acesso apenas à(s) turma(s) permitida(s), presença e relatórios próprios |

## 📁 Estrutura do Projeto

```
pgadms/
├── api.py                 # Backend Flask completo (RBAC, 2FA, mentoria)
├── admins.db              # Banco de dados separado para admins
├── db.sqlite3             # Banco de dados principal
├── index.html             # Painel Admin com sidebar e gestão completa
├── super.html             # Painel Super Admin com 2FA
├── mentoria.html          # Gestão de mentoria (Admin Global)
├── aluno_mentoria.html    # Detalhes do aluno com gráficos de evolução
├── forms.html             # Formulário para mentores responderem avaliações
├── offline.html           # Página offline com Service Worker
├── sw.js                  # Service Worker para cache e fallback
├── style.css              # Estilos globais do painel admin
├── 404.html               # Página personalizada de erro
├── vercel.json            # Configuração de deploy
├── presenca/              # Páginas de presença por turma (10 arquivos HTML)
├── uploads/               # Diretório para imagens de avisos
├── thumbnails/            # Miniaturas geradas automaticamente
└── test.py                # Reconhecimento facial (experimental)
```

## 📊 Recursos em Destaque

- ✅ **Registro offline** com sincronização automática
- ✅ **Validação de datas** por turma (dias específicos)
- ✅ **Relatórios mensais em Excel** com gráficos e filtros
- ✅ **Marcação em lote** ("Marcar todos presentes")
- ✅ **Metadados de auditoria** (quem criou/editou)
- ✅ **Mentoria socioemocional** com gráficos de evolução
- ✅ **Painel Super Admin** com 2FA e logs
- ✅ **Backup e restauração** completa dos dados
- ✅ **Design responsivo** para desktop e mobile

## 🤝 Contribuição

Contribuições são bem-vindas! Sinta-se à vontade para abrir issues ou pull requests.

1. Faça um fork do projeto
2. Crie sua branch de feature (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -m 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Abra um Pull Request

## 📄 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

## 🙏 Agradecimentos

- **Instituto Robert Bosch** — pela oportunidade e estrutura
- **Programa Formare 2025/2026** — alunos, professores e coordenadores que contribuíram com feedbacks
- **Erick Matheus Leguisamon** — desenvolvimento e manutenção voluntária

## 📞 Contato

- **Desenvolvedor:** Erick Matheus Leguisamon
- **E-mail:** erickleguisamon@gmail.com
- **LinkedIn:** [linkedin.com/in/erickleguisamon](https://www.linkedin.com/in/erickleguisamon/)
- **WhatsApp:** (41) 99823-9031

## 🔗 Links Úteis

- [Repositório no GitHub](https://github.com/erickmth/pgadms)
- [Sistema em Produção (Vercel)](https://pgadms.vercel.app)
- [API (PythonAnywhere)](https://erickmth.pythonanywhere.com)


 **Nota:** Este sistema é mantido voluntariamente e está em constante evolução. Sugestões e feedbacks são sempre bem-vindos!

