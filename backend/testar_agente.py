"""Teste dos 3 cenários do enunciado: rotina, urgência e ambiguidade."""
from app.agente import processar

CASOS = {
    "1. ROTINA": (
        "CLINICA BEM VIVER - RECEITUARIO. Paciente: Ana Beatriz Rocha, 61 anos. "
        "Uso oral: Losartana 50mg, tomar 1 comprimido ao dia. Metformina 850mg, "
        "tomar 1 comprimido apos o almoco e o jantar. Dr. Paulo Henrique Lima "
        "CRM-SP 98765. Data: 28/10/2026."
    ),
    "2. URGENCIA": (
        "HOSPITAL SANTA LUCIA - LAUDO DE EXAME RADIOLOGICO. Paciente: Carlos Eduardo "
        "Mendes, 52 anos. Solicitante: Dra. Renata Silveira CRM-SP 145892. Exame: "
        "Tomografia de Torax com contraste. Indicacao: Suspeita de embolia pulmonar "
        "aguda, dispneia subita. Achados: Falha de enchimento em arteria pulmonar "
        "principal direita compativel com TEP agudo. CONCLUSAO: Quadro compativel com "
        "Tromboembolismo Pulmonar Agudo. Sugere-se correlacao clinica urgente."
    ),
    "3. AMBIGUIDADE": (
        "RECEITA. Paciente: Jose R... (ilegivel). Tomar Amox... 500 ?? de ?? em ?? "
        "horas por ?? dias. Assinatura ilegivel, sem carimbo e sem CRM."
    ),
}

for nome, texto in CASOS.items():
    r = processar(documento_id=f"TESTE-{nome[0]}", texto=texto, canal_origem="Teste")
    d = r.decisao_roteamento
    print(f"\n===== {nome} =====")
    print("Status:      ", r.status)
    print("Tipo:        ", r.classificacao.tipo_documento.value)
    print("Prioridade:  ", r.classificacao.nivel_prioridade.value)
    print("Destino:     ", d.destino_principal.value)
    print("Secundários: ", [x.value for x in d.destinos_secundarios])
    print("Justificativa:", d.justificativa_roteamento)
    if d.notificacao_gerada:
        print("Notificação: ", d.notificacao_gerada.mensagem)