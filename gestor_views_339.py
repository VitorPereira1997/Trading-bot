"""Vistas de leitura. Os únicos dados privados são argumentos da sessão atual."""
from collections import Counter, defaultdict
from datetime import date
from base64 import b64encode
import re
import math

import pandas as pd
import streamlit as st

VIEWS = {
    'Distribuição': ['01 · Peso e retorno', '02 · Setores e extremos', '03 · Interior dos ETFs'],
    'Dividendos': ['04 · Dividendos por posição', '05 · Mapa mensal', '06 · Resumo e agenda'],
    'Desempenho': ['07 · Resultado pessoal', '08 · Comparação com índices', '09 · Extremos mensais'],
    'Carteira': ['10 · Posições abertas', '11 · Posições fechadas'],
    'Pontuação': ['12 · Fatores da carteira'],
}


def number(v):
    try:
        value = float(v)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def signed(v, unit='%'):
    n = number(v)
    return 'N/D' if n is None else (f'{n:+.2f}' if n else '0.00').replace('.', ',') + unit


def key(row):
    return str(row.get('Ticker XTB') or '').strip().upper(), number(row.get('Quantidade'))


def matched(positions, rows):
    counts = Counter(map(key, positions))
    by_key = defaultdict(list)
    for row in rows:
        by_key[key(row)].append(row)
    result = []
    for pos in positions:
        k = key(pos)
        candidates = by_key[k]
        row = candidates[0] if k[0] and k[1] and k[1] > 0 and counts[k] == len(candidates) == 1 else {}
        if row.get('Erro'):
            row = {}
        result.append((pos, row))
    return result


# Marcas locais: sem pedidos externos e sem substituir uma empresa desconhecida por outra.
BRANDS = {
    'AAPL': ('Apple', 'Apple', '#20242b', '#fff'),
    'ASML': ('ASML', 'ASML', '#132556', '#fff'),
    'GOOG': ('Alphabet', 'Google', '#fff', '#174ea6'),
    'GOOGL': ('Alphabet', 'Google', '#fff', '#174ea6'),
    'UBER': ('Uber', 'Uber', '#111', '#fff'),
    'ANET': ('Arista Networks', 'arista', '#0b538c', '#fff'),
    'NVDA': ('NVIDIA', 'NVIDIA', '#263500', '#e0ff96'),
    'AMD': ('AMD', 'AMD', '#241918', '#fff'),
    'BCP': ('Millennium BCP', 'Millennium', '#961046', '#fff'),
    'NOS': ('NOS', 'NOS', '#27242a', '#fff'),
    'VWCE': ('Vanguard FTSE All-World', 'Vanguard', '#8b1538', '#fff'),
    'QDVG': ('', 'QDVG', '#253875', '#fff'),
    'MSFT': ('Microsoft', '', '#fff', '#111'),
    'V': ('Visa', '', '#fff', '#21408a'),
    'NKE': ('Nike', '', '#fff', '#171717'),
}
ICONS = {
    'MSFT':'<path fill="#f25022" d="M0 0h11v11H0z"/><path fill="#7fba00" d="M13 0h11v11H13z"/><path fill="#00a4ef" d="M0 13h11v11H0z"/><path fill="#ffb900" d="M13 13h11v11H13z"/>',
    'NKE':'<path fill="#171717" d="M2 13q-3 11 9 4l13-9-16 6q-6 2-4-4z"/>',
    'V':'<text x="12" y="16" text-anchor="middle" font-family="sans-serif" font-size="9" font-weight="bold" fill="#21408a">VISA</text>',
    'AAPL':'<path fill="#fff" d="M16.8 3c.1 1.4-.7 2.7-1.5 3.5-.9.8-1.9 1.2-3 1.1.1-1.1.6-2.3 1.4-3.1.8-.9 2-1.4 3.1-1.5zm3.2 14.4c-.5 1.2-1.4 2.7-2.5 3.1-1 .4-1.9-.4-3.6-.4s-2.6.8-3.7.4c-1.8-.6-4-4.7-4-8 0-2.9 1.8-4.6 4-4.6 1.4 0 2.1.7 3.2.7 1.2 0 1.9-.7 3.4-.7 1.4 0 2.7.7 3.4 1.7-2.7 1.5-2.6 5.3.5 6.6z"/>',
}


def company(ticker, row):
    value = row.get('Empresa')
    if isinstance(value, str) and value.strip() and value.strip().upper() not in {'N/D', ticker.upper()}:
        return value.strip()[:85]
    return BRANDS.get(ticker.split('.')[0].upper(), ('',))[0]


def badge(t):
    base = t.split('.')[0].upper()
    _, label, bg, fg = BRANDS.get(base, ('', re.sub(r'[^A-Z0-9]', '', base)[:2] or '?', '#26374b', '#fff'))
    mark = ICONS.get(base)
    if mark is None:
        size = min(10, 38/max(1,len(label)))
        mark = f'<text x="12" y="12.5" dominant-baseline="middle" text-anchor="middle" fill="{fg}" font-family="sans-serif" font-size="{size}" font-weight="bold">{label}</text>'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="5" fill="{bg}"/><g transform="translate(2 2) scale(.833333)">{mark}</g></svg>'
    return f'![{base if base in BRANDS else ""}](data:image/svg+xml;base64,{b64encode(svg.encode()).decode()})'


def ui_text(value):
    # Botões aceitam Markdown; nomes e datas do armazenamento entram só como texto.
    return ''.join(chr(92)+ch if ch in chr(92)+"`*_{}[]()<>#+!|~" else ch for ch in ' '.join(str(value).split()))


def cards(items, detail, context, dense=False):
    if not items:
        return
    with st.container(key=('list_' if dense else 'grid_') + context):
        for i,(pos, row) in enumerate(items):
            ticker = str(pos.get('Ticker XTB') or 'N/D')
            delta = number(row.get('Variação dia %'))
            tone = 'flat' if delta in (None, 0) else 'up' if delta > 0 else 'down'
            direction = 'Sem cotação' if delta is None else 'Sem variação' if delta == 0 else 'Subida' if delta > 0 else 'Descida'
            arrow = '' if delta in (None,0) else '▲ ' if delta > 0 else '▼ '
            ref = ui_text(row.get('Data') or 'Sem data')
            name = ui_text(company(ticker,row))
            ticker_text = ui_text(ticker)
            label = f"{badge(ticker)} **{ticker_text}**  \n***{arrow}{signed(delta)}***  \n*{direction} · {ref}*"
            if name:
                label += f'  \n{name}'
            # Aplicar estilo ao contentor identificado, não ao wrapper interno do botão.
            with st.container(key=f'asset_{tone}_{context}_{i}'):
                if st.button(label,width='stretch',key=f'card_{tone}_{context}_{i}'):
                    detail(pos, row)


def allocation(items):
    values = [number(r.get('Valor atual EUR')) for _, r in items]
    if not values or any(v is None or v < 0 for v in values) or sum(values) <= 0:
        return []
    total = sum(values)
    return [(str(p.get('Ticker XTB')), v / total, r) for (p, r), v in zip(items, values) if v > 0]


def graphic(entries, bubbles):
    # Partições em unidades do viewBox. O raio das bolhas é proporcional à raiz do peso.
    pieces = []
    def split(group, x, y, w, h):
        if len(group) > 1:
            n = len(group) // 2
            f = sum(i[1] for i in group[:n]) / sum(i[1] for i in group)
            if w >= h:
                split(group[:n], x, y, w*f, h)
                split(group[n:], x+w*f, y, w*(1-f), h)
            else:
                split(group[:n], x, y, w, h*f)
                split(group[n:], x, y+h*f, w, h*(1-f))
            return
        title, weight, value = group[0]
        color = '#e3e6e4' if value in (None, 0) else ('#a4d7b5' if value >= 5 else '#d8efde') if value > 0 else ('#e5a99b' if value <= -5 else '#f5ded7')
        pieces.append({'Título':title,'Peso':f'{weight:.2%}','Retorno':signed(value), 'cor':color,
                       'x':x,'x2':x+w,'y':y,'y2':y+h,'peso':weight,
                       'ordem':len(pieces)})
    split(entries,0,0,600,220)
    encoding = {'tooltip':[{'field':field,'type':'nominal'} for field in ('Título','Peso','Retorno')],
                'color':{'field':'cor','type':'nominal','scale':None,'legend':None}}
    if bubbles:
        encoding.update(x={'field':'ordem','type':'ordinal','axis':None},
                        y={'value':85},size={'field':'peso','type':'quantitative',
                        'scale':{'domain':[0,1],'range':[0,4800]},'legend':None})
    else:
        for field in ('x','y'):
            encoding[field]={'field':field,'type':'quantitative','axis':None,
                             'scale':{'domain':[0,600 if field=='x' else 220]}}
            encoding[field+'2']={'field':field+'2'}
    spec={'height':200,'mark':{'type':'circle' if bubbles else 'rect','stroke':'white','cursor':'pointer'},
          'encoding':encoding, 'params':[{'name':'selecionada','select':{'type':'point','fields':['Título']}}]}
    event=st.vega_lite_chart(pd.DataFrame(pieces),spec,width='stretch',on_select='rerun',key='allocation_plot')
    selected=event.selection.get('selecionada',[])
    return selected[0].get('Título') if selected else None



def distribution(idx, items, detail):
    if idx == 3:
        from etf_holdings_preview import AS_OF, DATA, exposure, fund_id
        from decimal import Decimal
        funds = [p for p,r in items if (p.get('Tipo instrumento') or r.get('Tipo instrumento')) == 'ETF']
        if not funds:
            st.info('Não há ETFs identificados nas posições carregadas.')
            return
        index = st.selectbox('Fundo',range(len(funds)),format_func=lambda i:str(funds[i].get('Ticker XTB')))
        isin = fund_id(funds[index])
        if isin:
            label, url, rows = DATA[isin]
            covered = sum(Decimal(weight) for _,weight in rows)
            st.markdown(f'{label} · {isin} · composição de {AS_OF} · [Vanguard]({url})')
            st.metric('Cobertura: peso das 10 linhas conhecidas no fundo',f'{covered:.2f}%')
            st.dataframe([{'Emitente':name,'Peso no fundo':f'{weight}%'} for name,weight in rows],hide_index=True)
            st.caption('Cada linha representa um título publicado. Um emitente pode ter várias classes. Os pesos não foram reescalados.')
        else:
            st.info('Sem composição verificada para este fundo.')
        known, denominator, gaps, remaining = exposure(items)
        if known:
            st.subheader('Exposição conhecida por emitente')
            combined = []
            for name, by_source in known.items():
                direct = by_source.get('direto',Decimal(0))
                indirect = sum(value for key,value in by_source.items() if key != 'direto')
                total = direct+indirect
                if indirect:
                    combined.append((total,{'Emitente':name, 'Direta identificada':signed(direct,' €'),
                                            'Via ETFs identificados':signed(indirect,' €'), 'Total conhecido':signed(total,' €'),
                                            'Peso conhecido nas posições':signed(total*100/denominator) if denominator else 'N/D',
                                            'ETFs com linhas conhecidas':', '.join(DATA[i][0] for i in by_source if i!='direto')}))
            if combined:
                st.dataframe([row for _,row in sorted(combined,key=lambda x:x[0],reverse=True)],hide_index=True)
            st.caption('Estimativa parcial: usa a composição datada e os valores guardados das posições em EUR, que podem ser de outras datas. Só entram as linhas e as ações diretas identificadas. Não representa a sobreposição completa dos fundos.')
        if gaps or remaining:
            st.info(f'Posições sem avaliação em EUR ou fora do cálculo: {gaps}. Posições em ETFs sem composição identificada: {remaining}.')
        return
    alloc = allocation(items)
    if not alloc:
        st.info('Pesos indisponíveis. É necessária uma avaliação em EUR de cada quantidade e um total positivo.')
    if idx == 1 and alloc:
        period = st.selectbox('Retorno representado', ['Desde o preço médio','Variação diária'])
        field = 'P/L %' if period.startswith('Desde') else 'Variação dia %'
        mode = st.radio('Apresentação',['Mapa','Bolhas','Lista'],horizontal=True)
        entries = [(t,w,number(r.get(field))) for t,w,r in alloc]
        if st.checkbox('Agrupar posições abaixo de 3%'):
            small = [i for i in entries if i[1]<.03]
            entries = [i for i in entries if i[1]>=.03]
            if small:
                entries.append(('Outras',sum(i[1] for i in small),None))
        picked = graphic(entries,mode=='Bolhas') if mode != 'Lista' else None
        if picked:
            value = next((e for e in entries if e[0]==picked),None)
            if value:
                st.text(f'{picked} · peso {value[1]:.2%} · retorno {signed(value[2])}')
                selected_item=next(((p,r) for p,r in items if p.get('Ticker XTB')==picked),None)
                if selected_item and st.button('Abrir '+ui_text(picked),key='allocation_detail'):
                    detail(*selected_item)
        st.caption('Área = peso no total avaliado. Verde = subida; vermelho = descida. Tom mais intenso a partir de ±5%. Cinzento = zero ou N/D.')
        with st.expander('Ver valores e abrir uma posição', expanded=mode=='Lista'):
            st.dataframe([{'Título':t,'Peso':f'{w:.2%}','Retorno':signed(v)} for t,w,v in entries],hide_index=True)
            selected=st.selectbox('Abrir posição',range(len(items)),format_func=lambda i:str(items[i][0].get('Ticker XTB')))
            if st.button('Ver detalhe'):
                detail(*items[selected])
    if idx == 2:
        basis=st.radio('Classificação',['Por setor direto','Tempo em carteira'],horizontal=True)
        if basis=='Por setor direto' and alloc:
            sectors=defaultdict(float)
            for _,weight,row in alloc:
                sectors[str(row.get('Setor') or 'Sem classificação')]+=weight
            st.write('Distribuição direta por setor')
            st.bar_chart(pd.DataFrame([{'Setor':sector,'Peso (%)':weight*100} for sector,weight in sectors.items()]),x='Setor',y='Peso (%)',height=220,horizontal=True)
            st.caption('Usa a classificação das posições diretas, sem redistribuir todo o interior dos ETFs.')
        elif basis=='Tempo em carteira':
            ages=[]
            for p,_ in items:
                opened=pd.to_datetime(p.get('Data entrada'),errors='coerce')
                days=(date.today()-opened.date()).days if pd.notna(opened) else -1
                ages.append({'Título':str(p.get('Ticker XTB')),'Dias desde a entrada registada':days if days>=0 else None})
            if ages:
                st.dataframe(ages,hide_index=True)
        field = st.radio('Extremos desde o preço médio',['Em percentagem','Em euros'],horizontal=True)
        column = 'P/L %' if field=='Em percentagem' else 'P/L EUR aprox.'
        unit = '%' if field=='Em percentagem' else ' €'
        valid=[(p,r) for p,r in items if number(r.get(column)) is not None]
        if valid:
            for card,label,choose in zip(st.columns(2),('Melhor','Pior'),(max,min)):
                p,r=choose(valid,key=lambda pair:number(pair[1][column]))
                card.metric(f"{label} · {p.get('Ticker XTB')}",signed(r[column],unit))
        else:
            st.info('Sem avaliações guardadas suficientes para mostrar extremos.')
        st.caption(f'Cobertura do retorno escolhido: {len(valid)}/{len(items)} posições.')



MONTHS=('Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez')


def dividend_map(groups, year, month, totals):
    # Cores e rótulos mostram recebimentos observados, não meses presumidos a zero.
    values={m:float(totals(rows)[0]) for m,rows in groups.items()}
    top=max(values.values(),default=0)
    cells=[]
    for m,name in enumerate(MONTHS,1):
        value=values.get(m)
        intensity=value/top if value is not None and top>0 else 0
        style='style="background:#233347;color:#e4edf7"' if value is None else f'style="background:hsl(143 38% {87-33*intensity:.1f}%);color:#0e2621"'
        label='N/D' if value is None else signed(value,' €')
        active=' selected' if m==month else ''
        cells.append(f'<div class="dividend-cell{active}" {style}><b>{name}</b><span>{label}</span></div>')
    st.markdown('<style>.dividend-map{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.42rem}.dividend-cell{display:grid;padding:.42rem .25rem;justify-items:center;border-radius:.55rem;font-size:.75rem;text-align:center;overflow-wrap:anywhere}.dividend-cell.selected{outline:2px solid #89caff;outline-offset:1px}@media(max-width:550px){.dividend-map{grid-template-columns:repeat(4,minmax(0,1fr))}}</style><div class="dividend-map" role="group" aria-label="Dividendos líquidos em '+str(year)+'">'+''.join(cells)+'</div>',unsafe_allow_html=True)


def dividend_history(idx, items, cash_store=None):
    from cash_history import parse, totals
    from xtb_history_339 import checked, ledger as saved_ledger, merge
    def clear_preview():
        for name in ('cash_history_preview','cash_history_source','cash_history_upload','cash_history_eur',
                     'cash_history_year','cash_history_month','cash_history_save_draft'):
            st.session_state.pop(name, None)
        for name in list(st.session_state):
            if str(name).startswith('cash_history_eur_'):
                st.session_state.pop(name, None)

    with st.expander('Pré-visualizar histórico de movimentos'):
        st.caption('Carrega o Excel (.xlsx) que exportaste da XTB, sem o converter, ou usa o CSV do Gestor. A pré-visualização não guarda nada nem altera a carteira. Um Excel XTB reconhecido pode ser guardado depois de conferido.')
        with st.popover('Formato do CSV'):
            st.code('id;data;tipo;ticker;moeda;liquido;bruto;retencao')
            st.caption('CSV normalizado em EUR. Tipos: dividendo, deposito, levantamento, comissao, taxa. No dividendo, bruto e retenção são opcionais; se constarem do extrato, indica ambos.')
        upload = st.file_uploader('Ficheiro de movimentos', type=['xlsx','csv'], key='cash_history_upload')
        xlsx = upload is not None and upload.name.lower().endswith('.xlsx')
        confirmed = False
        if xlsx:
            confirmed = st.checkbox('Confirmo que a conta deste extrato XTB está em EUR', key='cash_history_eur_'+upload.file_id)
            st.caption('Confirma a moeda da conta, não a moeda das ações. Não é feita conversão cambial.')
        if st.button('Pré-visualizar movimentos', disabled=upload is None or (xlsx and not confirmed)):
            for name in ('cash_history_preview','cash_history_source','cash_history_year','cash_history_month','cash_history_save_draft'):
                st.session_state.pop(name, None)
            try:
                if xlsx:
                    from xtb_cash_339 import preview_with_ids
                    ledger, notes, account, movements = preview_with_ids(upload.getvalue(), confirmed)
                    st.session_state['cash_history_source'] = notes
                    st.session_state['cash_history_save_draft'] = (upload.file_id, account, movements)
                else:
                    ledger = parse(upload.getvalue())
                st.session_state['cash_history_preview'] = ledger
            except ValueError as err:
                st.error(str(err))
        if upload is not None or 'cash_history_preview' in st.session_state:
            st.button('Limpar pré-visualização', on_click=clear_preview)
    notes = st.session_state.get('cash_history_source')
    if notes is not None:
        skipped, suspect, summaries = notes
        st.caption('Excel XTB · Operações em numerário. Valores em EUR. O saldo líquido é o total dos créditos menos as retenções registadas no período; podem ter datas diferentes. Não é feita correspondência entre pagamentos e retenções.')
        if skipped or summaries:
            st.caption(f'Linhas não incluídas: {skipped} de outros movimentos (por exemplo, compras e vendas) e {summaries} de resumo.')
        if suspect:
            st.warning(f'{suspect} movimentos com indicação de dividendo ou retenção não foram reconhecidos. Confirma os totais no extrato.')
    ledger = st.session_state.get('cash_history_preview', ())
    active_xtb = notes is not None
    ready, read_saved, save_reviewed = cash_store or (False, lambda: None, None)
    try:
        saved = checked(read_saved())
    except ValueError as err:
        saved, ready = {}, False
        st.warning(str(err))
    draft = st.session_state.get('cash_history_save_draft')
    if draft and upload is not None and draft[0]==upload.file_id and confirmed:
        source_id, imported_account, movements = draft
        if not imported_account:
            st.info('A conta não foi identificada no extrato. Podes pré-visualizar, mas não guardar este Excel.')
        elif notes and notes[1]:
            st.warning('Não é possível guardar enquanto houver possíveis dividendos ou retenções por confirmar.')
        elif ready:
            try:
                _, added, duplicates = merge(saved, imported_account, movements)
            except ValueError as err:
                st.warning(str(err))
            else:
                with st.expander('Guardar histórico da XTB', expanded=bool(added)):
                    st.caption(f'{added} movimentos novos · {duplicates} já guardados. Serão guardados os valores e datas destes movimentos, não o Excel, nem a carteira.')
                    st.caption(f'Conta XTB · {imported_account[:8].upper()} (identificação interna do Gestor)')
                    st.dataframe([{'Data':day,'Tipo':'Retenção de dividendo' if kind=='dividendo' and net<0 else kind,
                                   'Título':ticker,'Valor em EUR':str(net)}
                                  for day,kind,ticker,net,_,_ in movements.values()],hide_index=True)

                    confirmed_save = st.checkbox('Conferi este extrato e quero guardar os movimentos reconhecidos',
                                                 key='cash_history_save_'+source_id)
                    if st.button('Confirmar e guardar histórico XTB',disabled=not added or not confirmed_save):
                        try:
                            added, duplicates = save_reviewed(imported_account,movements)
                        except ValueError as err:
                            st.error(str(err))
                        else:
                            st.success(f'{added} novos movimentos guardados no histórico XTB. {duplicates} já existiam.')
                            saved = checked(read_saved())
        else:
            st.info('Para guardar, é necessária a tua sessão individual com armazenamento privado disponível.')
    if saved:
        sources = ['Histórico XTB guardado'] if not ledger else ['Pré-visualização atual','Histórico XTB guardado']
        history_source = st.radio('Fonte do histórico', sources, horizontal=True, key='cash_history_mode')
        if history_source == 'Histórico XTB guardado':
            accounts = sorted(key for key in saved if saved[key])
            if accounts:
                account_key = st.selectbox('Conta XTB guardada', accounts, key='cash_history_account',
                                           format_func=lambda value: f'Conta XTB · {value[:8].upper()}')
                ledger, active_xtb = saved_ledger(saved, account_key), True
    if not ledger:
        return False
    years = sorted({row[0].year for row in ledger},reverse=True)
    year = st.selectbox('Ano',years,key='cash_history_year')
    annual = [row for row in ledger if row[0].year==year]
    dividends = [row for row in annual if row[1]=='dividendo']
    st.caption(f'Apenas os {len(ledger)} movimentos apresentados, de {ledger[0][0]:%d/%m/%Y} a {ledger[-1][0]:%d/%m/%Y}. A cobertura do extrato não foi confirmada.')
    if not dividends:
        st.info('Não há dividendos nas linhas fornecidas. Isto não confirma que não recebeste dividendos.')
    if idx == 4 and dividends:
        opened = {key(p)[0] for p,_ in items}
        by_ticker = defaultdict(list)
        for row in dividends:
            by_ticker[row[2]].append(row)
        total = totals(dividends)[0]
        def entry(ticker, rows):
            net, gross, tax = totals(rows)
            qty = [p for p,_ in items if key(p)[0]==ticker]
            cost = None
            if len(qty)==1:
                unit = number(qty[0].get('Preço médio'))
                amount = number(qty[0].get('Quantidade'))
                if unit and unit > 0 and amount and amount > 0 and qty[0].get('Moeda') == 'EUR':
                    cost = amount*unit
            return {'Título':ticker,'Situação':'Posição aberta' if ticker in opened else 'Sem posição aberta identificada',
                    'Líquido':signed(net,' €'),'Bruto':signed(gross,' €'),'Retenção':signed(tax,' €'),
                    'Peso nos dividendos importados':signed(net*100/total) if total>0 else 'N/D',
                    'Líquido / custo da posição aberta':signed(float(net)*100/cost) if cost else 'N/D'}
        state=st.radio('Posições',['Todas','Abertas','Sem posição aberta identificada'],horizontal=True)
        table=[entry(t, rs) for t,rs in sorted(by_ticker.items()) if state=='Todas' or (t in opened)==(state=='Abertas')]
        if table:
            st.dataframe(table,hide_index=True)
        else:
            st.info('Sem recebimentos importados para este filtro.')
        st.caption('O rácio líquido/custo compara os pagamentos importados com o custo atual, não é yield anual nem atribui dividendos a lotes. A ausência nas posições abertas não prova uma venda.')
    elif idx == 5:
        groups = defaultdict(list)
        for row in dividends:
            groups[row[0].month].append(row)
        selected = st.pills('Mês',range(1,13),format_func=lambda m:MONTHS[m-1],
                           default=max(groups,default=date.today().month),key='cash_history_month')
        dividend_map(groups,year,selected,totals)
        st.caption('Verde: valor líquido importado; cinzento: sem recebimentos no ficheiro para esse mês. N/D não significa zero.')
        details = groups.get(selected, [])
        if details:
            if active_xtb:
                st.dataframe([{'Data':r[0],'Título':r[2],'Movimento':'Retenção' if r[3]<0 else 'Crédito',
                               'Valor':signed(r[3],' €')} for r in details],hide_index=True)
            else:
                st.dataframe([{'Data':r[0],'Título':r[2],'Líquido':signed(r[3],' €')} for r in details],hide_index=True)
        else:
            st.info('Não há recebimentos importados neste mês.')
    elif idx == 6:
        if dividends:
            net, gross, tax = totals(dividends)
            for card,title,value in zip(st.columns(3),('Líquido recebido','Bruto','Retenção'),(net,gross,tax)):
                card.metric(title,signed(value,' €'))
            amounts = defaultdict(int)
            for row in dividends:
                amounts[row[2]] += row[3]
            leaders = sorted(ticker for ticker, value in amounts.items() if value == max(amounts.values()))
            st.text('Maior pagador por líquido: '+', '.join(leaders) if max(amounts.values()) > 0 else 'Maior pagador por líquido: N/D')
            months=len({row[0].month for row in dividends})
            if months:
                st.metric('Média por mês com recebimentos importados',signed(net/months,' €'))
                st.caption(f'{months} meses com registos. Não é uma média de todos os meses do ano.')
        for kind,title in (('deposito','Depósitos'),('levantamento','Levantamentos'),('comissao','Comissões'),('taxa','Taxas')):
            amounts = [row[3] for row in annual if row[1]==kind]
            st.write(f'{title}: {signed(sum(amounts)," €") if amounts else "N/D"}')
    return True


def render(idx, items, detail, calendar, symbol, prices, cash_store=None):
    if idx<=3:
        distribution(idx,items,detail)
    elif idx<=6:
        has_history = dividend_history(idx, items, cash_store)
        if idx==4 and not has_history:
            st.info('Para ver dividendos por título, pré-visualiza um ficheiro de movimentos na secção acima. Ter uma posição aberta não confirma recebimentos.')
        elif idx==5 and not has_history:
            year=st.number_input('Ano',min_value=1900,max_value=date.today().year,value=date.today().year)
            month=st.pills('Mês',range(1,13),format_func=lambda m:('Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez')[m-1],default=date.today().month) or date.today().month
            dividend_map({},year,month,lambda rows:None)
            st.info(f'{month:02d}/{year} · Sem registo verificável de dividendos recebidos.')
        elif idx==6:
            if not has_history:
                st.info('Bruto, retenção, líquido, maior pagador e médias indisponíveis. A carteira não contém um extrato de dividendos liquidados.')
            st.subheader('Agenda futura de dividendos')
            if items and st.button('Consultar agenda futura'):
                agenda, unavailable, failed = [], [], []
                for t,p in {str(p.get('Ticker XTB')):p for p,_ in items}.items():
                    try:
                        events=[e for e in calendar(p.get('Ticker técnico') or symbol(t)['source_ticker']) if e.startswith(('Ex-dividendo','Pagamento'))]
                        if not events:
                            unavailable.append(t)
                        for event in events:
                            kind, _, raw=event.partition(' · ')
                            agenda.append((raw,kind,t))
                    except Exception:
                        failed.append(t)
                for raw,kind,t in sorted(agenda):
                    st.write(f'{raw} · {kind} · {t}')
                if unavailable:
                    st.write('Sem data verificável: '+', '.join(unavailable))
                if failed:
                    st.write('Fonte indisponível: '+', '.join(failed))
                st.caption('Yahoo Finance · consulta em '+date.today().isoformat()+' · datas futuras sujeitas a revisão. Quantidade elegível e montante por confirmar.')
    elif idx==7:
        vals=[number(r.get('P/L EUR aprox.')) for _,r in items]
        columns=st.columns(2)
        columns[0].metric('Por realizar · avaliação guardada',signed(sum(vals),' €') if vals and all(v is not None for v in vals) else 'N/D')
        columns[1].metric('Realizado · vendas comprovadas','N/D')
        for col,title in zip(st.columns(2),('IRR · efeito dos teus fluxos','TWR · retorno sem efeito dos fluxos')):
            col.metric(title,'N/D')
        st.info('Para medir o retorno total faltam vendas realizadas, depósitos e levantamentos completos, e avaliações nas datas dos fluxos.')
    elif idx==8:
        st.caption('A comparação só é válida com o mesmo intervalo, moeda e tratamento dos dividendos.')
        for col,title in zip(st.columns(3),('Carteira','S&P 500','Nasdaq 100')):
            col.metric(title+' · retorno total','N/D')
        st.info('TWR e CAGR indisponíveis: faltam séries de retorno total comparáveis em EUR para a carteira e os índices.')
    elif idx==9:
        for col,title in zip(st.columns(2),('Melhor mês','Pior mês')):
            col.metric(title,'N/D')
        st.metric('Sequência de meses consecutivos','N/D')
        st.info('Faltam fechos mensais consecutivos com retornos comparáveis. Uma última avaliação não é um histórico mensal.')
    elif idx==11:
        for col,title in zip(st.columns(2),('Posições fechadas comprovadas','Resultado realizado')):
            col.metric(title,'N/D')
        st.info('Falta um histórico com data de fecho e resultado das vendas. Remover uma posição ou registar uma decisão não comprova uma venda.')
    elif idx==12:
        alloc=allocation(items)
        weights=max(alloc,key=lambda i:i[1]) if alloc else None
        cols=st.columns(2)
        cols[0].metric('Pontuação da carteira','N/D')
        cols[1].metric('Maior peso direto',f'{weights[1]:.1%}' if weights else 'N/D',help=str(weights[0]) if weights else None)
        if alloc:
            classified=sum(w for _,w,r in alloc if r.get('Setor') not in (None,'','N/D','Other'))
            st.caption(f'Cobertura setorial identificada: {classified:.1%} do valor avaliado.')
        st.info('Volatilidade e correlação precisam de séries sincronizadas. Qualidade precisa de fundamentais comparáveis e datados.')
        if items and st.button('Consultar 60 retornos diários em EUR'):
            series = {}
            for p,r in items:
                ticker = str(p.get('Ticker XTB'))
                if r.get('Moeda') != 'EUR' or ticker in series:
                    continue
                try:
                    source = p.get('Ticker técnico') or symbol(ticker)['source_ticker']
                    history = prices(source,'6mo','1d')['Close'].dropna()
                    history = history[history > 0].sort_index()
                    returns = history.pct_change(fill_method=None).dropna().tail(60)
                    if len(returns) == 60:
                        series[ticker] = returns
                except Exception:
                    continue
            st.caption(f'Yahoo Finance · fechos ajustados em EUR · {len(series)} títulos com 60 retornos · consulta {date.today().isoformat()}')
            if series:
                st.dataframe([{'Título':t,'Volatilidade diária':signed(v.std()*100),
                               'Último fecho':str(v.index[-1].date())} for t,v in series.items()],hide_index=True)
                aligned=pd.concat(series,axis=1,join='inner').dropna()
                if len(series)>=2 and len(aligned)>=60:
                    st.write('Correlação entre títulos · 60 sessões comuns')
                    st.dataframe(aligned.tail(60).corr())
                else:
                    st.caption('Correlação indisponível: faltam dois títulos com 60 retornos nas mesmas datas.')
