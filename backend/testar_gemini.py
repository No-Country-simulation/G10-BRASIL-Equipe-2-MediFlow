"""Teste do extrator com o laudo de exemplo do enunciado."""
from app.extrator import extrair

LAUDO = (
    "HOSPITAL SANTA LUCIA - LAUDO DE EXAME RADIOLOGICO. Paciente: Carlos Eduardo "
    "Mendes, 52 anos. Solicitante: Dra. Renata Silveira CRM-SP 145892. Exame: "
    "Tomografia de Torax com contraste. Indicacao: Suspeita de embolia pulmonar "
    "aguda, dispneia subita. Achados: Falha de enchimento em arteria pulmonar "
    "principal direita compativel com TEP agudo. CONCLUSAO: Quadro compativel com "
    "Tromboembolismo Pulmonar Agudo. Sugere-se correlacao clinica urgente."
)

resultado = extrair(texto=LAUDO)
print(resultado.model_dump_json(indent=2))