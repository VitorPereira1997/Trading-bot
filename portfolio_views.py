"""Vistas de leitura. Os únicos dados privados são argumentos da sessão atual."""
from collections import Counter, defaultdict
from datetime import date
from base64 import b64encode
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


def badge(t):
    base = t.split('.')[0]
    icons = {
        'MSFT':'<path fill="#f25022" d="M0 0h11v11H0z"/><path fill="#7fba00" d="M13 0h11v11H13z"/><path fill="#00a4ef" d="M0 13h11v11H0z"/><path fill="#ffb900" d="M13 13h11v11H13z"/>',
        'NKE':'<path fill="#171717" d="M2 13q-3 11 9 4l13-9-16 6q-6 2-4-4z"/>',
        'V':'<text x="0" y="16" font-size="10" font-weight="bold" fill="#21408a">VISA</text>',
    }
    if base not in icons:
        return base[:2] or '—'
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'+icons[base]+'</svg>'
    return '![](data:image/svg+xml;base64,'+b64encode(svg.encode()).decode()+')'



def cards(items, detail, context, dense=False):
    if not items:
        return
    with st.container(key=('list_' if dense else 'grid_') + context):
        for i,(pos, row) in enumerate(items):
            ticker = str(pos.get('Ticker XTB') or 'N/D')
            delta = number(row.get('Variação dia %'))
            tone = 'flat' if delta in (None, 0) else 'up' if delta > 0 else 'down'
            state = 'Sem cotação diária' if delta is None else 'Sem variação' if delta == 0 else 'Subida' if delta > 0 else 'Descida'
            source = 'Avaliação guardada' if row else 'Sem avaliação correspondente'
            label = f"{badge(ticker)}  **{ticker}** · {state} {signed(delta)}  \n{row.get('Data') or 'Sem data'} · {source}"
            if st.button(label,width='stretch',key=f'card_{tone}_{context}_{i}'):
                detail(pos)


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
                st.write(f'{picked} · peso {value[1]:.2%} · retorno {signed(value[2])}')
        st.caption('Área = peso no total avaliado. Verde = subida; vermelho = descida. Tom mais intenso a partir de ±5%. Cinzento = zero ou N/D.')
        st.dataframe([{'Título':t,'Peso':f'{w:.2%}','Retorno':signed(v)} for t,w,v in entries],hide_index=True)
        default=next((i for i,(p,_) in enumerate(items) if p.get('Ticker XTB')==picked),0)
        selected=st.selectbox('Abrir posição',range(len(items)),index=default,format_func=lambda i:str(items[i][0].get('Ticker XTB')))
        if st.button('Ver detalhe'):
            detail(items[selected][0])
    if idx == 2:
        if alloc:
            sectors=defaultdict(float)
            for _,weight,row in alloc:
                sectors[str(row.get('Setor') or 'Sem classificação')]+=weight
            st.write('Distribuição direta por setor')
            st.dataframe([{'Setor':s,'Peso':f'{w:.2%}'} for s,w in sectors.items()],hide_index=True)
        valid=[(p,r) for p,r in items if number(r.get('P/L %')) is not None]
        if valid:
            for label,choose in [('Melhor',max),('Pior',min)]:
                p,r=choose(valid,key=lambda pair:number(pair[1]['P/L %']))
                st.write(f"{label} por retorno desde o preço médio · {p.get('Ticker XTB')} · {signed(r['P/L %'])} · {signed(r.get('P/L EUR aprox.'),' €')}")
        st.caption(f'Cobertura do retorno: {len(valid)}/{len(items)} posições.')
        for p,_ in items:
            opened=pd.to_datetime(p.get('Data entrada'),errors='coerce')
            days=(date.today()-opened.date()).days if pd.notna(opened) else -1
            st.text(f"{p.get('Ticker XTB')} · "+(f'{days} dias desde a entrada registada' if days>=0 else 'Data de entrada indisponível'))



def dividend_history(idx, items):
    from cash_history import parse, totals
    with st.expander('Pré-visualizar histórico de movimentos'):
        st.caption('CSV normalizado em EUR, apenas nesta sessão. Não aceita o Excel nativo da XTB. Inclui apenas montantes liquidados; não alteres as posições.')
        st.code('id;data;tipo;ticker;moeda;liquido;bruto;retencao')
        st.caption('Tipos: dividendo, deposito, levantamento, comissao, taxa. Para dividendos, bruto e retenção são opcionais, mas devem vir juntos quando constarem do extrato.')
        upload = st.file_uploader('Ficheiro de movimentos', type=['csv'], key='cash_history_upload')
        if st.button('Pré-visualizar movimentos', disabled=upload is None):
            try:
                st.session_state['cash_history_preview'] = parse(upload.getvalue())
            except ValueError as err:
                st.session_state.pop('cash_history_preview', None)
                st.error(str(err))
        if st.button('Limpar pré-visualização', disabled='cash_history_preview' not in st.session_state):
            st.session_state.pop('cash_history_preview', None)
    ledger = st.session_state.get('cash_history_preview', ())
    if not ledger:
        return False
    dividends = [row for row in ledger if row[1]=='dividendo']
    st.caption(f'Apenas os {len(ledger)} movimentos importados, de {ledger[0][0]:%d/%m/%Y} a {ledger[-1][0]:%d/%m/%Y}. A cobertura do extrato não foi confirmada.')
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
        st.dataframe([entry(t, rs) for t,rs in sorted(by_ticker.items())],hide_index=True)
        st.caption('O rácio líquido/custo compara os pagamentos importados com o custo atual, não é yield anual nem atribui dividendos a lotes. A ausência nas posições abertas não prova uma venda.')
    elif idx == 5 and dividends:
        years = sorted({row[0].year for row in dividends},reverse=True)
        year = st.selectbox('Ano',years,key='cash_history_year')
        selected = st.pills('Mês',range(1,13),default=1,key='cash_history_month')
        groups = defaultdict(list)
        for row in dividends:
            if row[0].year == year:
                groups[row[0].month].append(row)
        st.bar_chart(pd.DataFrame([{'Mês':f'{m:02d}','Líquido em EUR':float(totals(rs)[0])} for m,rs in sorted(groups.items())]),x='Mês',y='Líquido em EUR')
        st.caption('Mostra só meses com movimentos importados. Um mês em falta não equivale a zero.')
        details = groups.get(selected, [])
        if details:
            st.dataframe([{'Data':r[0],'Título':r[2],'Líquido':signed(r[3],' €')} for r in details],hide_index=True)
        else:
            st.info('Não há recebimentos importados neste mês.')
    elif idx == 6:
        if dividends:
            net, gross, tax = totals(dividends)
            for title,value in zip(('Líquido recebido','Bruto','Retenção'),(net,gross,tax)):
                st.metric(title,signed(value,' €'))
            amounts = defaultdict(int)
            for row in dividends:
                amounts[row[2]] += row[3]
            leaders = sorted(ticker for ticker, value in amounts.items() if value == max(amounts.values()))
            st.write('Maior pagador por líquido: '+', '.join(leaders))
        for kind,title in (('deposito','Depósitos'),('levantamento','Levantamentos'),('comissao','Comissões'),('taxa','Taxas')):
            amounts = [row[3] for row in ledger if row[1]==kind]
            st.write(f'{title}: {signed(sum(amounts)," €") if amounts else "N/D"}')
    return True


def render(idx, items, detail, calendar, symbol, prices):
    if idx<=3:
        distribution(idx,items,detail)
    elif idx<=6:
        has_history = dividend_history(idx, items)
        if idx==4 and not has_history:
            state=st.radio('Posições',['Abertas','Fechadas'],horizontal=True)
            if state=='Abertas' and items:
                st.selectbox('Título',[str(p.get('Ticker XTB')) for p,_ in items])
            st.info('Peso nos dividendos e yield sobre custo indisponíveis. Faltam recebimentos atribuídos por posição e custo elegível.')
        elif idx==5 and not has_history:
            year=st.number_input('Ano',min_value=1900,max_value=date.today().year,value=date.today().year)
            month=st.pills('Mês',range(1,13),format_func=lambda m:('Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez')[m-1],default=date.today().month) or date.today().month
            st.info(f'{month:02d}/{year} · Sem registo verificável de dividendos recebidos.')
        elif idx==6:
            if not has_history:
                st.info('Bruto, retenção, líquido, maior pagador e médias indisponíveis. A carteira não contém um extrato de dividendos liquidados.')
            if items and st.button('Consultar agenda futura'):
                for p,_ in items:
                    t=p.get('Ticker XTB')
                    try:
                        events=[e for e in calendar(p.get('Ticker técnico') or symbol(t)['source_ticker']) if e.startswith(('Ex-dividendo','Pagamento'))]
                        st.write(f"{t} · "+(' / '.join(events) or 'Sem data verificável'))
                    except Exception:
                        st.write(f'{t} · Fonte indisponível')
                st.caption('Yahoo Finance · consulta em '+date.today().isoformat()+' · datas futuras sujeitas a revisão. Quantidade elegível e montante por confirmar.')
    elif idx in (7,8,9):
        st.selectbox('Período',['Ano em curso','Últimos 12 meses','Desde o início'])
        if idx==7:
            vals=[number(r.get('P/L EUR aprox.')) for _,r in items]
            st.metric('Resultado por realizar aproximado',signed(sum(vals),' €') if vals and all(v is not None for v in vals) else 'N/D')
            st.info('Resultado total, IRR e TWR indisponíveis. Faltam avaliações nas datas dos fluxos, depósitos e levantamentos completos.')
        elif idx==8:
            st.info('TWR e CAGR comparáveis com S&P 500 e Nasdaq 100 indisponíveis. Faltam séries de retorno total com a mesma moeda, período e tratamento de dividendos.')
        else:
            st.info('Melhor e pior mês, extremos anuais e sequência indisponíveis. Faltam fechos consecutivos com retornos comparáveis.')
    elif idx==11:
        st.info('Fechos, datas de saída e resultado realizado indisponíveis. Remover uma posição ou registar uma decisão não comprova uma venda.')
    elif idx==12:
        alloc=allocation(items)
        if alloc:
            t,w,_=max(alloc,key=lambda i:i[1])
            st.metric('Maior peso direto',f'{w:.1%}',help=str(t))
            classified=sum(w for _,w,r in alloc if r.get('Setor') not in (None,'','N/D','Other'))
            st.caption(f'Cobertura setorial identificada: {classified:.1%} do valor avaliado.')
        st.info('Nota indisponível. Volatilidade e correlação precisam de séries sincronizadas; qualidade precisa de fundamentais comparáveis e datados.')

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
