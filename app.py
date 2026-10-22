import hashlib
import io
import json
import os
from datetime import date
from pathlib import Path
from zipfile import ZipFile, BadZipFile

import streamlit as st
from PIL import Image, UnidentifiedImageError
from database import connect, save, search

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('BANCO_DATA_DIR', str(ROOT / 'data'))).resolve()
UPLOADS = DATA / 'uploads'
UPLOADS.mkdir(parents=True, exist_ok=True)
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))


def attachment(upload, kind):
    raw = upload.getvalue()
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError('Cada arquivo deve ter no máximo 10 MB.')
    if kind == 'image':
        try:
            with Image.open(io.BytesIO(raw)) as img:
                img.verify()
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in ('PNG', 'JPEG'):
                    raise ValueError('Use imagens PNG ou JPEG.')
                extension = '.png' if img.format == 'PNG' else '.jpg'
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError('Imagem inválida.') from exc
    else:
        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                if 'word/document.xml' not in archive.namelist():
                    raise ValueError('Arquivo Word inválido.')
        except BadZipFile as exc:
            raise ValueError('Arquivo Word inválido.') from exc
        extension = '.docx'
    name = hashlib.sha256(raw).hexdigest() + extension
    (UPLOADS / name).write_bytes(raw)
    return name


def select(label, options, value=None):
    options = list(dict.fromkeys(options + ([value] if value and value not in options else [])))
    return st.selectbox(label, options, index=options.index(value) if value in options else 0)


def editor(db, current=None):
    q = current or {}
    with st.form('question_editor', clear_on_submit=False):
        statement = st.text_area('Enunciado *', value=q.get('statement', ''), height=200,
                                 help='Texto simples para consulta e busca. Para preservar equações e formatação, anexe o Word original.')
        docx = st.file_uploader('Arquivo Word original (opcional)', type=['docx'])
        if q.get('docx'):
            st.caption('O Word atual será mantido se você não enviar outro.')
        images = st.file_uploader('Figuras (opcional)', type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
        remove_images = st.checkbox('Remover as figuras atuais') if q.get('images') else False
        contents = st.multiselect('Conteúdo *', list(dict.fromkeys(CONFIG['conteudos'] + q.get('contents', []))), default=q.get('contents', []))
        col1, col2 = st.columns(2)
        with col1:
            school_year = select('Ano escolar *', CONFIG['anos'], q.get('school_year'))
            stage = select('Etapa *', CONFIG['etapas'], q.get('stage'))
        with col2:
            exam = select('Prova *', CONFIG['provas'], q.get('exam'))
            year_text = st.text_input('Ano de aplicação *', value=str(q.get('application_year', date.today().year)), max_chars=4)
        latex = st.text_area('Código LaTeX (opcional)', value=q.get('latex', ''), height=120,
                             help='Guardado como código, sem compilação de documentos ou TikZ.')
        submitted = st.form_submit_button('Salvar questão', type='primary')
    if submitted:
        if not statement.strip() or not contents:
            st.error('Preencha o enunciado e selecione ao menos um conteúdo.')
            return
        if not year_text.isdecimal() or not 1900 <= int(year_text) <= 2100:
            st.error('Digite um ano de aplicação entre 1900 e 2100.')
            return
        try:
            image_names = [] if remove_images else list(q.get('images', []))
            image_names.extend(attachment(image, 'image') for image in images)
            docx_name = attachment(docx, 'docx') if docx else q.get('docx')
            number = save(db, dict(statement=statement.strip(), contents=contents, school_year=school_year,
                stage=stage, exam=exam, application_year=int(year_text), latex=latex,
                images=image_names, docx=docx_name), q.get('id'))
            st.success(f'Questão {number} salva.')
        except ValueError as exc:
            st.error(str(exc))


st.set_page_config(page_title='Banco de questões', page_icon='📚', layout='wide')
st.title('Banco de questões de Matemática')
page = st.sidebar.radio('Navegação', ['Início', 'Cadastrar questão', 'Banco de questões'], key='navigation')
with connect(DATA / 'questions.sqlite3') as db:
    if page == 'Início':
        st.write('Cadastre questões ou consulte o acervo da escola usando o menu lateral.')
        st.metric('Questões cadastradas', db.execute('SELECT COUNT(*) FROM questions').fetchone()[0])
        left, right = st.columns(2)
        with left:
            st.button('Cadastrar questão', on_click=lambda: st.session_state.update(navigation='Cadastrar questão'))
            st.write('Enunciado, Word original, figuras, classificação e LaTeX opcional.')
        with right:
            st.button('Banco de questões', on_click=lambda: st.session_state.update(navigation='Banco de questões'))
            st.write('Busque por ano escolar, etapa, prova, conteúdo e palavras do enunciado.')
    elif page == 'Cadastrar questão':
        editor(db)
    else:
        a, b, c = st.columns(3)
        with a:
            school_year = st.selectbox('Ano escolar', [''] + CONFIG['anos'], format_func=lambda x: x or 'Todos')
        with b:
            stage = st.selectbox('Etapa', [''] + CONFIG['etapas'], format_func=lambda x: x or 'Todas')
        with c:
            exam = st.selectbox('Prova', [''] + CONFIG['provas'], format_func=lambda x: x or 'Todas')
        contents = st.multiselect('Conteúdo', CONFIG['conteudos'])
        st.caption('Ao marcar vários conteúdos, aparecem questões com pelo menos um deles.')
        keyword = st.text_input('Palavra ou trecho no enunciado')
        results = search(db, school_year, stage, exam, contents, keyword)
        st.write(f'{len(results)} questão(ões) encontrada(s).')
        chosen = st.selectbox('Editar questão', [None] + [q['id'] for q in results], format_func=lambda n: 'Selecione para editar' if n is None else f'Questão {n}')
        if chosen is not None:
            editor(db, next(q for q in results if q['id'] == chosen))
        for q in results:
            with st.expander(f"Questão {q['id']} · {q['school_year']} · {', '.join(q['contents'])}"):
                st.text(q['statement'])
                st.caption(f"{q['stage']} · {q['exam']} · Aplicação: {q['application_year']}")
                for name in q['images']:
                    st.image(str(UPLOADS / name))
                if q['docx']:
                    st.download_button('Baixar Word original', (UPLOADS / q['docx']).read_bytes(),
                        file_name=f"questao_{q['id']}.docx", key=f"docx_{q['id']}")
                if q['latex']:
                    st.code(q['latex'], language='latex')
