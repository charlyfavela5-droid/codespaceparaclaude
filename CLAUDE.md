# Codespace controlado por Claude

- Entorno: GitHub Codespace de Carlos (Visión Agencia). Responde en español mexicano casual, directo y accionable.
- Claude Code ya esta instalado. Tienes permiso para correr comandos, editar archivos, usar git y gestionar puertos con gh.
- Antes de borrar datos, cambiar secretos o poner puertos publicos, confirma con Carlos.
- Nunca imprimas ni subas tokens o llaves al repo.

## Propósito del harness (Carlos, 25 nov)
Todas las terminales existen para una sola cosa: cumplir lo que Carlos prometió a sus clientes, a quienes le escribieron estos días y a los prospectos (campaña gratis: 3 imágenes y 1 video, el mismo día). Lo más urgente primero; las imágenes de prospectos van muy rápido. El estado de todos vive en supervisor/ESTADO_CLIENTES.md: léelo al empezar cada vuelta.

## Investigación con agente gratis (no gastes Claude en leer)
Toda lectura pesada (chats de WhatsApp, logs largos, transcripciones, buscar qué se prometió) se delega al investigador gratis en Modal (Groq: gpt-oss-120b / qwen, rota solo):
    python /workspaces/codespaceparaclaude/scripts/gratis.py "tarea concreta" archivo1 archivo2
    comando_que_baja_el_chat | python /workspaces/codespaceparaclaude/scripts/gratis.py "tarea"
Claude solo decide, verifica los datos clave contra el original y produce. Si el gratis falla dos veces, entonces sí lee tú.

## Primer impulso (Carlos, 25 nov 11:15 pm)
Carlos solo aprueba el PRIMER IMPULSO de cada terminal: al arrancar, cada agente le muestra en 5 líneas su objetivo, la promesa que va a cumplir y el primer paso. Cuando Carlos diga "sí", el agente maneja solo el resto: investiga con el gratis, produce, itera con Glimmer hasta 8 y sigue con /loop sin volver a pedir permiso por cada paso (incluye GPU de imágenes; video con MiniMax solo si la terminal es de video y ya está en su plan aprobado).
Solo vuelve a Carlos cuando: (1) la pieza llegó a 8 y hay borrador de entrega listo, (2) falta material que solo el cliente puede dar (1 pregunta corta), o (3) algo costaría dinero fuera del plan. Los mensajes a clientes siempre quedan como borrador listo para enviar.
