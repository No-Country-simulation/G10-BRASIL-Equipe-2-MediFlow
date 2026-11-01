"""Teste da integração com o OCI: grava um documento e o resultado da triagem."""
from app.agente import processar
from app.armazenamento import listar, salvar_original, salvar_resultado

DOC_ID = "DOC-TESTE-OCI-001"
LAUDO = (
    "HOSPITAL SANTA LUCIA - LAUDO DE EXAME RADIOLOGICO. Paciente: Carlos Eduardo "
    "Mendes, 52 anos. Solicitante: Dra. Renata Silveira CRM-SP 145892. Exame: "
    "Tomografia de Torax com contraste. CONCLUSAO: Quadro compativel com "
    "Tromboembolismo Pulmonar Agudo. Sugere-se correlacao clinica urgente."
)

print("Enviando original:", salvar_original(DOC_ID, LAUDO.encode("utf-8"), "txt", "text/plain"))

resposta = salvar_resultado(processar(documento_id=DOC_ID, texto=LAUDO, canal_origem="Pronto_Socorro"))
print("Armazenamento:", resposta.armazenamento_oci.model_dump())

print("\nArquivos no bucket:")
for nome in listar():
    print(" -", nome)