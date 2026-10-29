"""Farol de alinhamento das datas finais das unidades no DW."""


def avaliar_atualizacao(unidades, esperadas=None):
    unidades = list(unidades)
    presentes = {unidade['unidade_id'] for unidade in unidades}
    for identificador in esperadas or []:
        if identificador not in presentes:
            unidades.append({'unidade_id': identificador, 'unidade': identificador,
                             'ultima_data_disponivel': None})
    datas = [unidade.get('ultima_data_disponivel') for unidade in unidades]
    conhecidas = [data for data in datas if data is not None]
    referencia = max(conhecidas) if conhecidas else None
    alinhadas = bool(datas) and len(conhecidas) == len(datas) and len(set(conhecidas)) == 1
    resultados = []
    for unidade in unidades:
        ultima_data = unidade.get('ultima_data_disponivel')
        if ultima_data is None:
            cor, status = 'cinza', 'Sem data disponível'
        elif alinhadas:
            cor, status = 'verde', 'Atualizada'
        elif ultima_data < referencia:
            cor, status = 'vermelho', 'Data final divergente'
        else:
            cor, status = 'amarelo', 'Aguardando demais cargas'
        resultados.append({**unidade, 'cor': cor, 'status': status})
    return resultados
