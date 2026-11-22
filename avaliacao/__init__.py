"""Suíte de avaliação e rastreamento de experimentos da consultoria.

Este pacote fica fora de `app/` de propósito: não é código de produção, não
entra na imagem Docker (o Dockerfile copia apenas `app/`, `dados/` e os dois
entrypoints) e usa dependências só de desenvolvimento, listadas em
`requirements-avaliacao.txt`.

Ele responde a uma pergunta objetiva: **a mudança que fiz melhorou ou piorou a
consultoria?** Para isso, cada alteração de prompt, agente, RAG ou grafo pode
ser medida por uma suíte fixa de casos com expectativas verificáveis.
"""
