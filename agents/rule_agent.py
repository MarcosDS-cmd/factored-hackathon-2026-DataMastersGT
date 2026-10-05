"""
No-LLM fallback agent ("modo determinístico") — Factored Hackathon 2026, Team DataMastersGT

Why it exists: the demo must never depend on an external API being up (or on a key being configured).
This agent plays the role of the LLM with a transparent state machine + our own intent classifier and
language detector, and calls the SAME tools through the SAME dispatch_tool_call — so every permission,
limit and audit record is identical to the LLM mode. The UI always shows which mode answered.

It is intentionally simple (regex + templates). It is not a replacement for the LLM's language
understanding; it is the safety net that keeps the controlled-automation guarantees demonstrable.
"""

from __future__ import annotations

import re
import unicodedata

from agent_core import EstadoConversacion, dispatch_tool_call

# ---------------------------------------------------------------------------
# Language-specific texts
# ---------------------------------------------------------------------------
TXT = {
    "es": {
        "pedir_id": "Con gusto te ayudo con tu disputa. Para proteger tu cuenta, ¿me compartes tu número de documento y tu nombre completo?",
        "pedir_doc": "Gracias, {nombre}. ¿Me compartes también tu número de documento?",
        "pedir_nombre": "Gracias. ¿Me confirmas tu nombre completo tal como aparece en tu documento?",
        "id_fallo": "No pude verificar tu identidad con esos datos ({motivo}). Revisa el número de documento y tu nombre completo. Te quedan {n} intento(s).",
        "id_bloqueo": "No pude verificar tu identidad después de varios intentos. Por seguridad te transfiero con un agente humano (referencia {ref}).",
        "id_inactivo": "Tu cuenta no está activa, así que este caso lo debe atender un agente humano. Ya te transferí (referencia {ref}).",
        "id_ok": "Listo {nombre}, verifiqué tu identidad. ",
        "pedir_monto": "¿Cuál es el monto del cargo que no reconoces? Si no lo recuerdas, estos son tus movimientos más recientes:\n{lista}\nPuedes responder con el número de la lista.",
        "sin_movs": "¿Cuál es el monto aproximado del cargo que no reconoces?",
        "no_encontrado": "No encuentro ningún cargo de aproximadamente {monto} en tu cuenta. No voy a abrir un caso sobre un cargo que no puedo confirmar. ¿Me das la fecha o el comercio, o prefieres que te pase con un agente humano?",
        "varias": "Encontré {n} cargos parecidos:\n{lista}\n¿Cuál es el que no reconoces? Responde con el número.",
        "AUTO_APROBADO": "Abrí el caso {caso} por el cargo de {monto} en {comercio}. Como está dentro del límite de resolución automática, el reembolso quedó **aprobado**. Lo verás reflejado en tu cuenta en 24–48 horas.",
        "PENDIENTE_REVISION": "Abrí el caso {caso} por el cargo de {monto} en {comercio}. Por el monto no puedo aprobarlo automáticamente, así que queda **en revisión estándar**; te contactaremos en un máximo de 5 días hábiles.",
        "ESCALADO_A_HUMANO": "Abrí el caso {caso} por el cargo de {monto} en {comercio}. Este caso necesita **revisión de un agente humano** ({motivo}). Ya le pasé todo el contexto, no tendrás que repetir nada.",
        "no_soportado": "Este asistente solo gestiona disputas por cargos no reconocidos y tu mensaje parece ser sobre otro tema ({intencion}). No quiero darte una respuesta inventada: ¿quieres que te transfiera con un agente humano que pueda ayudarte?",
        "humano": "Entiendo. Te transfiero con un agente humano con todo el contexto de esta conversación (referencia {ref}). Te contactarán en breve.",
        "inyeccion": "No puedo cambiar mis reglas ni los límites de aprobación: esas decisiones las aplica el sistema del banco, no yo. ",
        "decision_final": "La decisión del caso {caso} ({decision}) es final y no puedo modificarla. Si no estás de acuerdo, puedo transferirte con un agente humano.",
        "cerrado": "Tu caso {caso} ya está registrado. ¿Hay otro cargo que quieras disputar?",
        "sesion": "Tu sesión expiró por inactividad. Por seguridad, ¿me confirmas de nuevo tu número de documento y nombre completo?",
        "seleccion_invalida": "No identifiqué cuál de los cargos es. Responde con el número de la lista (1–{n}).",
        "duplicado": "Ese cargo ya tiene una disputa abierta ({caso}). No hace falta abrir otra.",
        "no_se_pudo": "No pude completar esa acción ({motivo}). ¿Quieres que te transfiera con un agente humano?",
    },
    "pt": {
        "pedir_id": "Claro, eu ajudo com a sua contestação. Para proteger sua conta, pode me informar o número do seu documento e seu nome completo?",
        "pedir_doc": "Obrigado, {nombre}. Pode me informar também o número do seu documento?",
        "pedir_nombre": "Obrigado. Pode confirmar seu nome completo como aparece no documento?",
        "id_fallo": "Não consegui verificar sua identidade com esses dados ({motivo}). Confira o número do documento e seu nome completo. Restam {n} tentativa(s).",
        "id_bloqueo": "Não consegui verificar sua identidade após várias tentativas. Por segurança vou transferir você para um atendente humano (referência {ref}).",
        "id_inactivo": "Sua conta não está ativa, então este caso precisa de um atendente humano. Já transferi (referência {ref}).",
        "id_ok": "Pronto {nombre}, verifiquei sua identidade. ",
        "pedir_monto": "Qual é o valor da cobrança que você não reconhece? Se não lembrar, estas são suas transações mais recentes:\n{lista}\nVocê pode responder com o número da lista.",
        "sin_movs": "Qual é o valor aproximado da cobrança que você não reconhece?",
        "no_encontrado": "Não encontro nenhuma cobrança de aproximadamente {monto} na sua conta. Não vou abrir um caso sobre uma cobrança que não consigo confirmar. Pode me dizer a data ou o estabelecimento, ou prefere falar com um atendente humano?",
        "varias": "Encontrei {n} cobranças parecidas:\n{lista}\nQual delas você não reconhece? Responda com o número.",
        "AUTO_APROBADO": "Abri o caso {caso} para a cobrança de {monto} em {comercio}. Como está dentro do limite de resolução automática, o reembolso foi **aprovado**. Ele aparecerá na sua conta em 24–48 horas.",
        "PENDIENTE_REVISION": "Abri o caso {caso} para a cobrança de {monto} em {comercio}. Pelo valor não posso aprová-lo automaticamente, então ele fica **em análise padrão**; entraremos em contato em até 5 dias úteis.",
        "ESCALADO_A_HUMANO": "Abri o caso {caso} para a cobrança de {monto} em {comercio}. Este caso precisa de **análise de um atendente humano** ({motivo}). Já passei todo o contexto, você não precisará repetir nada.",
        "no_soportado": "Este assistente só trata contestações de cobranças não reconhecidas e sua mensagem parece ser sobre outro assunto ({intencion}). Não quero inventar uma resposta: quer que eu transfira você para um atendente humano?",
        "humano": "Entendo. Vou transferir você para um atendente humano com todo o contexto desta conversa (referência {ref}). Entrarão em contato em breve.",
        "inyeccion": "Não posso mudar minhas regras nem os limites de aprovação: essas decisões são aplicadas pelo sistema do banco, não por mim. ",
        "decision_final": "A decisão do caso {caso} ({decision}) é final e não posso alterá-la. Se não concordar, posso transferir você para um atendente humano.",
        "cerrado": "Seu caso {caso} já está registrado. Há outra cobrança que você queira contestar?",
        "sesion": "Sua sessão expirou por inatividade. Por segurança, pode confirmar novamente seu documento e nome completo?",
        "seleccion_invalida": "Não identifiquei qual das cobranças é. Responda com o número da lista (1–{n}).",
        "duplicado": "Essa cobrança já tem uma contestação aberta ({caso}). Não é preciso abrir outra.",
        "no_se_pudo": "Não consegui concluir essa ação ({motivo}). Quer que eu transfira você para um atendente humano?",
    },
    "en": {
        "pedir_id": "Happy to help with your dispute. To protect your account, could you share your document number and your full name?",
        "pedir_doc": "Thanks, {nombre}. Could you also share your document number?",
        "pedir_nombre": "Thanks. Could you confirm your full name as it appears on your document?",
        "id_fallo": "I couldn't verify your identity with those details ({motivo}). Please check the document number and full name. {n} attempt(s) left.",
        "id_bloqueo": "I couldn't verify your identity after several attempts. For your security I'm handing you over to a specialist (reference {ref}).",
        "id_inactivo": "Your account isn't active, so a specialist needs to handle this case. I've already handed it over (reference {ref}).",
        "id_ok": "Thanks {nombre}, your identity is verified. ",
        "pedir_monto": "What's the amount of the charge you don't recognize? If you're not sure, these are your most recent transactions:\n{lista}\nYou can reply with the number from the list.",
        "sin_movs": "What's the approximate amount of the charge you don't recognize?",
        "no_encontrado": "I can't find any charge of about {monto} on your account, and I won't open a case for a charge I can't confirm. Can you tell me the date or the merchant, or would you prefer to talk to a specialist?",
        "varias": "I found {n} similar charges:\n{lista}\nWhich one don't you recognize? Reply with the number.",
        "AUTO_APROBADO": "I opened case {caso} for the {monto} charge at {comercio}. It's within the automatic resolution limit, so your refund is **approved**. You'll see it in your account within 24–48 hours.",
        "PENDIENTE_REVISION": "I opened case {caso} for the {monto} charge at {comercio}. I can't approve this amount automatically, so it's now **under standard review**; we'll get back to you within 5 business days.",
        "ESCALADO_A_HUMANO": "I opened case {caso} for the {monto} charge at {comercio}. This case needs **review by a specialist** ({motivo}). I've passed on the full context, so you won't have to repeat anything.",
        "no_soportado": "This assistant only handles disputes about charges you don't recognize, and your message seems to be about something else ({intencion}). I don't want to guess an answer: would you like me to connect you with a specialist?",
        "humano": "Understood. I'm connecting you with a specialist, along with the full context of this conversation (reference {ref}). They'll contact you shortly.",
        "inyeccion": "I can't change my rules or the approval limits: those decisions are enforced by the bank's system, not by me. ",
        "decision_final": "The decision on case {caso} ({decision}) is final and I can't change it. If you disagree, I can connect you with a specialist.",
        "cerrado": "Your case {caso} is already registered. Is there another charge you'd like to dispute?",
        "sesion": "Your session expired due to inactivity. For your security, please sign in again.",
        "seleccion_invalida": "I couldn't tell which charge you mean. Reply with the number from the list (1–{n}).",
        "duplicado": "That charge already has an open dispute ({caso}). There's no need to open another one.",
        "no_se_pudo": "I couldn't complete that action ({motivo}). Would you like me to connect you with a specialist?",
    },
}

DECISION_TXT = {
    "es": {"AUTO_APROBADO": "reembolso aprobado", "PENDIENTE_REVISION": "en revisión", "ESCALADO_A_HUMANO": "con un agente humano"},
    "pt": {"AUTO_APROBADO": "reembolso aprovado", "PENDIENTE_REVISION": "em análise", "ESCALADO_A_HUMANO": "com um atendente humano"},
    "en": {"AUTO_APROBADO": "refund approved", "PENDIENTE_REVISION": "under review", "ESCALADO_A_HUMANO": "with a specialist"},
}

MOTIVOS_EN = {"Amount": "amount above the limit", "Reception channel": "regulatory channel",
              "Suspected fraud": "suspected fraud", "High risk": "high risk"}
INTENT_EN = {"Product": "products", "Complaint": "a service complaint", "Technical": "a technical issue",
             "Commercial": "promotions", "Retention": "closing products"}

MOTIVOS_ES = {"Amount": "monto superior al límite", "Reception channel": "canal regulador",
              "Suspected fraud": "sospecha de fraude", "High risk": "riesgo alto"}
MOTIVOS_PT = {"Amount": "valor acima do limite", "Reception channel": "canal regulador",
              "Suspected fraud": "suspeita de fraude", "High risk": "risco alto"}
INTENT_ES = {"Product": "productos", "Complaint": "una queja de servicio", "Technical": "un problema técnico",
             "Commercial": "promociones", "Retention": "cancelación de productos"}
INTENT_PT = {"Product": "produtos", "Complaint": "uma reclamação de atendimento", "Technical": "um problema técnico",
             "Commercial": "promoções", "Retention": "cancelamento de produtos"}

RE_HUMANO = re.compile(r"\b(humano|persona|agente|asesor|supervisor|atendente|pessoa|alguien real|operador|human|person|agent|representative|specialist|real person)\b")
RE_ENOJO = re.compile(r"(verguenza|vergonha|harto|cansad|pesimo|pessimo|inaceptable|inaceitavel|estafa|robo|roubo|ladr|demand|abogado|advogado|superintendencia|banco central|procon|condusef|ridiculous|unacceptable|outrageous|lawyer|sue you|scam|terrible service)")
RE_INYECCION = re.compile(r"(ignora|ignore|olvida|esquece|desconsidera|sin limite|sem limite|override|system prompt|instrucciones|instrucoes|eres un|voce e um|modo admin|apruebalo ya|aprova agora|aprueba igual|aprove mesmo assim|soy el gerente|sou o gerente|you are now|disregard|approve it anyway|approve it now|i am the manager|i'm the manager|admin mode)")
RE_TRX = re.compile(r"\bTRX-[A-Z0-9]{10,30}\b")
RE_DOC = re.compile(r"\b(?!TRX)([A-Za-z]{0,3}-?\d[\d.\-]{5,14}\d)\b")
RE_NOMBRE = re.compile(r"(?:me llamo|mi nombre es|soy|nombre:|me chamo|meu nome e|meu nome é|sou|nome:|my name is|i am|i'm)\s+([A-Za-zÁÉÍÓÚÑÜáéíóúñüÂÊÔÃÕÇâêôãõç' ]{3,60})", re.I)
RE_MONTO = re.compile(r"(r\$|us\$|\$|usd|cop|mxn|ars|brl)?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(dolares|dólares|dollars|usd|pesos|reais|cop|mxn|ars)?", re.I)
STOP_NOMBRE = re.compile(r"\s+(?:y|e|con|com|mi|meu|minha|documento|dni|cc|ce|pasaporte|passaporte|numero|número|cpf|rg|quiero|quero|tengo|tenho)\b.*$", re.I)


def _plain(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def _a_float(s: str) -> float:
    s = s.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", s) or re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(".", "").replace(",", ".")   # 1.200,50 / 300,00
    else:
        s = s.replace(",", "")                      # 1,200.50
    return float(s)


def extraer_documento(texto: str):
    m = RE_DOC.search(texto)
    return m.group(1) if m else None


RE_MAYUS = re.compile(r"\b([A-ZÁÉÍÓÚÑÜÂÊÔÃÕÇ][a-záéíóúñüâêôãõç']+(?:\s+(?:de\s+|del\s+|da\s+|dos\s+)?[A-ZÁÉÍÓÚÑÜÂÊÔÃÕÇ][a-záéíóúñüâêôãõç']+)+)")
NO_NOMBRE = {"hola", "buenas", "buenos", "ola", "olá", "oi", "bom", "boa", "es", "sou", "soy", "mi", "meu", "el", "la",
             "documento", "dni", "gracias", "obrigado", "tardes", "dias", "días", "noches", "tarde", "dia",
             "hi", "hello", "my", "i", "thanks", "document"}


def extraer_nombre(texto: str):
    m = RE_NOMBRE.search(texto)
    if m:
        nombre = STOP_NOMBRE.sub("", m.group(1)).strip(" ,.")
        if len(nombre.split()) >= 2:
            return nombre
    # fallback: the longest run of Capitalized Words (e.g. "N4350845, Emilio Muñoz Castro")
    mejores = []
    for run in RE_MAYUS.findall(texto):
        palabras = [w for w in run.split() if w.lower() not in NO_NOMBRE]
        if len(palabras) >= 2:
            mejores.append(" ".join(palabras))
    return max(mejores, key=len) if mejores else None


def extraer_monto(texto: str, doc: str | None = None):
    t = texto.replace(doc, " ") if doc else texto
    mejor = None
    for m in RE_MONTO.finditer(t):
        cur_pre, num, cur_post = m.group(1), m.group(2), m.group(3)
        try:
            v = _a_float(num)
        except ValueError:
            continue
        if v <= 0 or v > 1_000_000_000:  # COP amounts reach tens of millions
            continue
        contexto = _plain(t[max(0, m.start() - 25):m.start()])
        con_marca = bool(cur_pre or cur_post) or re.search(r"(cargo|cobro|cobranca|pago|pagamento|compra|monto|valor|retiro|de|charge|payment|purchase|amount|of|for|was)\s*$", contexto)
        if re.fullmatch(r"\d{1,2}", num) and not (cur_pre or cur_post):
            continue  # "el 3 de junio", list choices
        if con_marca:
            return v
        mejor = mejor or v
    return mejor


def _fmt_monto(v) -> str:
    return f"US${float(v):,.2f}" if v is not None else "—"


TIPOS = {"en": {"Withdrawal": "Withdrawal", "Transfer": "Transfer", "Purchase": "Purchase", "Payment": "Payment", "Deposit": "Deposit"},
         "es": {"Withdrawal": "Retiro", "Transfer": "Transferencia", "Purchase": "Compra", "Payment": "Pago", "Deposit": "Depósito"},
         "pt": {"Withdrawal": "Saque", "Transfer": "Transferência", "Purchase": "Compra", "Payment": "Pagamento", "Deposit": "Depósito"}}


def describir(t: dict, lang: str = "es") -> str:
    if t.get("merchant_name"):
        return t["merchant_name"]
    tipo = TIPOS[lang].get(t.get("transaction_type"), t.get("transaction_type") or "")
    return f"{tipo} ({t.get('channel')})" if t.get("channel") else tipo or "—"


def _lista(txns, n=5, lang="es") -> str:
    return "\n".join(f"{i}. {str(t['transaction_date'])[:10]} · {describir(t, lang)} · {_fmt_monto(t['amount_usd'])}"
                     + (f" ({t['amount']:,.2f} {t['currency']})" if t.get("currency") and t["currency"] != "USD" else "")
                     for i, t in enumerate(txns[:n], 1))


class AgenteReglas:
    """Deterministic agent. All memory lives in EstadoConversacion (server side)."""

    def responder(self, mensaje: str, estado: EstadoConversacion, nlu: dict) -> str:
        lang = estado.idioma if estado.idioma in TXT else "es"
        tx = TXT[lang]
        plain = _plain(mensaje)
        pre = ""
        if nlu.get("inyeccion"):
            pre = tx["inyeccion"]

        mem = estado.__dict__.setdefault("_reglas", {"monto": None, "candidatas": None, "lista_movs": None})
        verificado = bool(estado.session and estado.session.verificado)
        doc = None if verificado else extraer_documento(mensaje)
        monto = extraer_monto(mensaje, doc)
        if monto and not mem["candidatas"] and not mem["lista_movs"]:
            mem["monto"] = monto

        # 1) explicit request for a human or clear anger -> escalate (always allowed)
        if (RE_HUMANO.search(plain) or RE_ENOJO.search(plain)) and not nlu.get("inyeccion"):
            motivo = "Cliente solicita agente humano" if RE_HUMANO.search(plain) else "Cliente muy molesto / amenaza de reclamo formal"
            caso_id = estado.casos[-1]["caso_id"] if estado.casos else ""
            r = dispatch_tool_call("escalar_a_humano", {"caso_id": caso_id, "motivo": motivo}, estado)
            return pre + tx["humano"].format(ref=estado.handoff["handoff_id"] if estado.handoff else r["caso_id"])

        # 2) identification
        sesion = estado.session
        if sesion is not None and sesion.verificado and sesion.expirada():
            sesion.verificado = False
            return tx["sesion"]
        if sesion is None or not sesion.verificado:
            nombre = extraer_nombre(mensaje) or mem.get("nombre")
            doc = doc or mem.get("doc")
            if nombre:
                mem["nombre"] = nombre
            if doc:
                mem["doc"] = doc
            if not doc and not nombre:
                if nlu.get("intencion") not in (None, "Transactional") and nlu.get("confianza", 0) >= 0.6 and not monto:
                    return pre + self._no_soportado(estado, nlu, tx, lang)
                return pre + tx["pedir_id"]
            if not doc:
                return pre + tx["pedir_doc"].format(nombre=nombre.split()[0].title())
            if not nombre:
                return pre + tx["pedir_nombre"]
            r = dispatch_tool_call("identificar_cliente", {"document_number": doc, "nombre_completo": nombre}, estado)
            mem["doc"] = mem["nombre"] = None
            if not r.get("ok"):
                if r.get("motivo") == "MAX_INTENTOS_EXCEDIDO":
                    return tx["id_bloqueo"].format(ref=estado.handoff["handoff_id"])
                if r.get("motivo") == "CLIENTE_INACTIVO":
                    h = dispatch_tool_call("escalar_a_humano", {"caso_id": "", "motivo": "Cliente inactivo"}, estado)
                    return tx["id_inactivo"].format(ref=estado.handoff["handoff_id"])
                motivo = {"es": {"CLIENTE_NO_ENCONTRADO": "documento no encontrado", "DATOS_NO_COINCIDEN": "el nombre no coincide"},
                          "pt": {"CLIENTE_NO_ENCONTRADO": "documento não encontrado", "DATOS_NO_COINCIDEN": "o nome não confere"},
                          "en": {"CLIENTE_NO_ENCONTRADO": "document not found", "DATOS_NO_COINCIDEN": "the name doesn't match"},
                          }[lang].get(r["motivo"], r["motivo"])
                return tx["id_fallo"].format(motivo=motivo, n=r.get("intentos_restantes", 1))
            pre += tx["id_ok"].format(nombre=r["cliente"]["first_name"].split()[0].title())
            return pre + self._buscar(estado, mem, tx, lang)

        # 2b) the customer points at a specific transaction id (e.g. the portal's "Dispute" button)
        m_trx = RE_TRX.search(mensaje)
        if m_trx:
            r = dispatch_tool_call("consultar_transacciones_recientes",
                                   {"customer_id": estado.session.customer_id, "dias": 90}, estado)
            txn = next((t for t in r.get("transacciones", []) if t["transaction_id"] == m_trx.group(0)), None) if r.get("ok") else None
            if txn:
                mem["monto"] = mem["candidatas"] = mem["lista_movs"] = None
                return pre + self._abrir(estado, txn, tx, lang)

        # 3) verified: a case already open in this conversation?
        if estado.casos and not monto and not mem["candidatas"] and not mem["lista_movs"]:
            c = estado.casos[-1]
            if nlu.get("inyeccion") or re.search(r"(aprueb|aprob|aprov|reembols|devuel|insist|por que|por que no|cambia|muda|approve|refund|why|change|reconsider)", plain):
                return pre + tx["decision_final"].format(caso=c["caso_id"], decision=DECISION_TXT[lang].get(c["decision"], c["decision"]))
            if nlu.get("intencion") not in ("Transactional",) and nlu.get("confianza", 0) >= 0.6:
                return pre + self._no_soportado(estado, nlu, tx, lang)
            return pre + tx["cerrado"].format(caso=c["caso_id"])

        # 4) choosing among candidates / recent movements
        for clave in ("candidatas", "lista_movs"):
            lista = mem[clave]
            if lista:
                sel = re.search(r"(?<![\d.,$])\b([1-9])\b(?![\d.,])", plain)
                elegido = None
                if monto and monto >= 10:
                    sel = None  # the customer quoted an amount, not a list position
                    for t in lista:
                        if (t.get("amount_usd") and abs(t["amount_usd"] - monto) <= 0.05 * t["amount_usd"]) or \
                                (t.get("amount") and abs(t["amount"] - monto) <= 0.01 * t["amount"]):
                            elegido = t
                if not elegido and sel and int(sel.group(1)) <= len(lista):
                    elegido = lista[int(sel.group(1)) - 1]
                else:
                    if not monto:
                        for t in lista:
                            if t.get("merchant_name") and _plain(t["merchant_name"]) in plain:
                                elegido = t
                    if monto and not elegido:  # amount given but not in the list -> full search (may be ambiguous)
                        mem[clave] = None
                        mem["monto"] = monto
                        return pre + self._buscar(estado, mem, tx, lang)
                if not elegido:
                    return pre + tx["seleccion_invalida"].format(n=len(lista))
                mem[clave] = None
                return pre + self._abrir(estado, elegido, tx, lang)

        if not monto and nlu.get("intencion") not in (None, "Transactional") and nlu.get("confianza", 0) >= 0.6:
            return pre + self._no_soportado(estado, nlu, tx, lang)
        return pre + self._buscar(estado, mem, tx, lang)

    # -----------------------------------------------------------------------
    def _no_soportado(self, estado, nlu, tx, lang):
        estado.registrar("fuera_de_alcance", intencion=nlu.get("intencion"), confianza=nlu.get("confianza"))
        nombre = {"es": INTENT_ES, "pt": INTENT_PT, "en": INTENT_EN}[lang].get(nlu.get("intencion"), nlu.get("intencion"))
        return tx["no_soportado"].format(intencion=nombre)

    def _buscar(self, estado, mem, tx, lang):
        cid = estado.session.customer_id
        if not mem.get("monto"):
            r = dispatch_tool_call("consultar_transacciones_recientes", {"customer_id": cid, "dias": 60}, estado)
            movs = [t for t in r.get("transacciones", []) if t.get("transaction_type") != "Deposit"][:5] if r.get("ok") else []
            if not movs:
                return tx["sin_movs"]
            mem["lista_movs"] = movs
            return tx["pedir_monto"].format(lista=_lista(movs, lang=lang))
        monto = mem["monto"]
        mem["monto"] = None
        r = dispatch_tool_call("buscar_cargo_disputado", {"customer_id": cid, "monto_aprox": monto}, estado)
        if not r.get("ok"):
            return tx["sesion"] if r.get("motivo") == "SESSION_EXPIRED" else tx["no_se_pudo"].format(motivo=r.get("motivo"))
        if not r["encontrada"]:
            estado.registrar("ambiguo", motivo="cargo_no_encontrado", monto=monto)
            return tx["no_encontrado"].format(monto=f"{monto:,.2f}")
        cands = r["candidatas"]
        if len(cands) > 1:
            mem["candidatas"] = cands[:5]
            estado.registrar("ambiguo", motivo="varias_candidatas", n=len(cands))
            return tx["varias"].format(n=len(cands[:5]), lista=_lista(cands, lang=lang))
        return self._abrir(estado, cands[0], tx, lang)

    def _abrir(self, estado, txn, tx, lang):
        cid = estado.session.customer_id
        dispatch_tool_call("calcular_riesgo_caso", {"monto_reclamado": txn["amount_usd"], "categoria": "Transactions",
                                                    "canal_recepcion": estado.canal, "es_reincidente": False}, estado)
        r = dispatch_tool_call("abrir_caso_disputa", {"customer_id": cid, "transaction_id": txn["transaction_id"],
                                                      "monto_usd": txn["amount_usd"], "categoria": "Transactions",
                                                      "canal_recepcion": estado.canal}, estado)
        if not r.get("ok"):
            if r.get("motivo") == "CASO_DUPLICADO":
                caso = estado.session.casos_abiertos.get(txn["transaction_id"], "")
                return tx["duplicado"].format(caso=caso)
            return tx["sesion"] if r.get("motivo") == "SESSION_EXPIRED" else tx["no_se_pudo"].format(motivo=r.get("motivo"))
        mapa = {"es": MOTIVOS_ES, "pt": MOTIVOS_PT, "en": MOTIVOS_EN}[lang]
        motivos = ", ".join(next((v for k, v in mapa.items() if m.startswith(k)), m) for m in r["motivos_escalacion"])
        return tx[r["decision"]].format(caso=r["caso_id"], monto=_fmt_monto(r["monto_usd"]),
                                        comercio=describir(txn, lang), motivo=motivos)


def correr_conversacion_reglas(mensaje: str, estado: EstadoConversacion, nlu: dict) -> str:
    return AgenteReglas().responder(mensaje, estado, nlu)
