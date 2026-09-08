"""The submission classifier: which KIND of consequential thing a form send is.

DESIGN 5.4a. `form_submit` used to cover "run this search" and "delete my
account" with one class, one prompt, and one sentence, which is the whole of
the author's complaint: the gate could not name its own harm, so it fired on
research and taught people to click through prompts. This module splits the
class into the four that CAN name their harm, and the residual keeps the old
name.

    payment_form        money moves. Added 2026-09-08: the class already
                        existed and was decided from FIELDS alone, so a
                        stored-card confirm step, which carries no card
                        field at all, was not a payment to this build.
    credential_submit   an authentication attempt the human did not
                        authorize. Credential blindness refuses the tool
                        WRITING a password; nothing refused it PRESSING the
                        button that sends one a human typed.
    broadcast_submit    the human's name is attached to words they did not
                        write, irreversibly, in public or in someone's inbox.
    destructive_submit  something is deleted, cancelled, revoked, or
                        deactivated.
    legal_assent        the human is bound by terms nobody read to them.

**The discipline is the payment classifier's, and it is binding here**
(DESIGN 5.4): state the CLASS and not the instance, use multiple signals, and
let page-authored text classify UP into a gate but never DOWN out of one.

**Multi-lingual from day one.** The payment list was English-only until
re-attack 2 (B1) put a live PAN into `Kartennummer`. That lesson does not
need learning twice, so every vocabulary here ships English, German, French,
Spanish, Italian, Portuguese, Korean, Japanese, and Chinese, and the folding
is `credentials._fold`'s Latin-only diacritic strip, which leaves Hangul and
kana recomposed and intact.

**Where the vocabularies live, and why not in the projection too.** The
payment vocabulary is mirrored in `projection/payment.js` and pinned equal by
test, because the in-page code makes the payment DECISION. These
vocabularies are not mirrored: the projection computes FACTS (the submitter's
accessible name, the form's action path, the checkbox labels, whether a
textarea or a recipient field is present, all squashed by the same
script-preserving squash payment.js uses) and this module makes the decision
from them. One list, one place, nothing to drift. The mirror that IS pinned
is the squash itself, which is the part both sides must agree on.

**Boundary-aware, because `delete` inside `deleted items` is a label and not
a verb on this button.** Latin terms match as whole space-delimited words
against the squashed haystack. Terms written in scripts that do not space
their words (Hangul, kana, Han) match as substrings, because there are no
boundaries to respect and requiring them would mean shipping a vocabulary
that can never fire.

**A gate that fires on everything is the same failure as a gate that fires on
nothing, from the other side.** Every battery over this module carries a
CONTROL ARM: an ordinary POST search that must stay ungated in the same run.
"""

from __future__ import annotations

import re

from . import credentials

# --------------------------------------------------------------- the squash

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_NONWORD = re.compile(r"[^\w]+|_+", re.UNICODE)

#: Scripts that do not space their words. A term written wholly in these
#: matches as a substring; anything else matches on word boundaries.
_UNSPACED = (
    (0x1100, 0x11FF), (0x3040, 0x30FF), (0x3130, 0x318F), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xA960, 0xA97F), (0xAC00, 0xD7FF), (0xF900, 0xFAFF),
)


def _unspaced_char(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _UNSPACED)


def squash(*parts) -> str:
    """Every string that can name a control, reduced to space-delimited
    lowercase words, padded with one space at each end so a whole-word test
    is a substring test.

    This is `credentials.payment_haystack`'s body with a caller-supplied
    field list instead of a descriptor's, and `projection/consent.js`'s
    `ksSquashConsent` is its in-page twin. `test_credentials.py`'s mirror
    battery pins the two."""
    raw = " ".join(str(p) for p in parts if p)
    raw = _CAMEL.sub(r"\1 \2", raw)[:400]
    folded = credentials._fold(raw.lower())
    return " " + _NONWORD.sub(" ", folded).strip() + " "


def _term_is_unspaced(term: str) -> bool:
    letters = [c for c in term if c.isalnum()]
    return bool(letters) and all(_unspaced_char(c) for c in letters)


def matches(hay: str, terms: tuple[str, ...]) -> str | None:
    """The first term in `terms` present in `hay`, or None.

    A Latin term must stand as its own word (or its own run of words, for a
    phrase); an unspaced-script term matches as a substring because its
    language writes no boundaries to match on."""
    if not hay:
        return None
    for term in terms:
        if _term_is_unspaced(term):
            if term in hay:
                return term
        elif f" {term} " in hay:
            return term
    return None


# --------------------------------------------------------- the vocabularies
#
# SOURCING NOTE, and it is the same one payment.js carries: the non-English
# terms are the labels real pages in those markets write on these buttons,
# not dictionary translations of the English word. A term that no page uses
# costs nothing and protects nobody; a term that every page uses for an
# ordinary submit would gate the whole web.

#: STRONG send terms: a submitter named one of these is sending something to
#: other people whatever else the form contains, so this tier fires on the
#: submitter's name or the form's action path ALONE.
BROADCAST_STRONG: tuple[str, ...] = (
    # English
    "post", "publish", "tweet", "reply", "comment", "share", "invite",
    "message", "dm", "broadcast", "announce", "notify", "email",
    # German
    "posten", "veroffentlichen", "kommentieren", "kommentar", "antworten",
    "teilen", "einladen", "nachricht",
    # French
    "publier", "commenter", "commentaire", "repondre", "partager",
    "inviter",
    # Spanish
    "publicar", "comentar", "comentario", "responder", "compartir",
    "invitar", "mensaje",
    # Italian
    "pubblica", "pubblicare", "commenta", "commentare", "rispondi",
    "condividi", "invita", "messaggio",
    # Portuguese
    "comentario", "compartilhar", "partilhar", "convidar", "mensagem",
    # Korean
    "게시", "댓글", "답글", "공유", "초대", "메시지", "쪽지",
    # Japanese
    "投稿", "返信", "コメント", "共有", "招待", "メッセージ",
    # Chinese (simplified then traditional)
    "发布", "回复", "评论", "分享", "邀请", "消息",
    "發佈", "發布", "回覆", "評論", "邀請", "訊息",
)

#: BARE SEND terms. `Enviar` is the standard Spanish label on an ordinary
#: search button and `Senden` is the German one, so these fire only WITH a
#: corroborating structural signal (a textarea, or a recipient-shaped field).
#: That is the payment classifier's multi-signal rule applied here: one
#: signal that also names ordinary furniture is not a classification.
BROADCAST_SEND: tuple[str, ...] = (
    "send", "send it", "senden", "absenden", "envoyer", "enviar", "invia",
    "inviare", "전송", "보내기", "보내", "送信", "发送", "發送",
)

#: Terms that name the destruction. `cancel` is here and it is the one term
#: in this table that also names an ordinary dialog button, which is why the
#: destructive class is scoped to SUBMITTERS and action paths rather than to
#: any control on the page.
DESTRUCTIVE_TERMS: tuple[str, ...] = (
    # English
    "delete", "remove", "erase", "wipe", "purge", "destroy", "deactivate",
    "revoke", "terminate", "unsubscribe", "cancel", "close account",
    "delete account", "uninstall", "discard", "shut down",
    # German
    "loschen", "entfernen", "kundigen", "deaktivieren", "widerrufen",
    "abbestellen", "sperren",
    # French
    "supprimer", "effacer", "retirer", "annuler", "desactiver", "revoquer",
    "resilier", "se desinscrire",
    # Spanish
    "eliminar", "borrar", "quitar", "cancelar", "desactivar", "revocar",
    "dar de baja",
    # Italian
    "elimina", "eliminare", "cancella", "cancellare", "rimuovi",
    "rimuovere", "disattiva", "revoca", "annulla",
    # Portuguese
    "excluir", "apagar", "remover", "desativar", "revogar",
    # Korean
    "삭제", "제거", "탈퇴", "해지", "취소", "비활성화", "철회",
    # Japanese
    "削除", "消去", "解約", "退会", "取消", "取り消し", "無効化",
    # Chinese
    "删除", "移除", "注销", "取消", "停用", "撤销",
    "刪除", "註銷", "撤銷",
)

#: STRONG payment terms: a submitter or an action path named one of these is
#: moving money whatever fields the form carries, so this tier fires alone.
#:
#: WHY THIS TABLE EXISTS AT ALL, and it is the finding that put it here
#: (verify round 2026-09-08, V-19). Payment was a FIELD property and only a
#: field property: `credentials.is_payment_field` and the census's
#: `form_payment` flag, both of which read INPUTS. A modern checkout confirm
#: step has no card input on it, because the card was captured on a previous
#: page or lives in the wallet, so a `method="get"` form whose only control
#: says "Pay now" carried no payment signal at all, classified as the
#: residual `form_submit`, was admitted by the GET rule as query-shaped, and
#: submitted with zero prompts. A "Delete my account" button on the exact
#: same page shape gated correctly. It was the word "Pay" that nothing read.
#:
#: The terms are the labels checkout pages actually print on that button, in
#: the nine languages the rest of this module ships. Terms that also name
#: ordinary furniture are NOT here: bare `subscribe` is a newsletter on most
#: of the web, bare `order` is a sort direction, bare `continue` is every
#: second form on the internet. Those live in the corroborated tier below.
PAYMENT_TERMS: tuple[str, ...] = (
    # English
    "pay", "pay now", "pay securely", "pay with", "make payment",
    "confirm payment", "complete payment", "submit payment", "checkout",
    "check out", "place order", "place your order", "confirm order",
    "complete order", "submit order", "buy", "buy now", "buy it now",
    "purchase", "complete purchase", "confirm purchase", "donate",
    "donation", "give now", "pledge", "add payment", "billing",
    "charge my card", "start subscription", "confirm subscription",
    "payment", "charge", "charges", "paypal", "checkout session",
    # German
    "bezahlen", "jetzt bezahlen", "zur kasse", "kostenpflichtig bestellen",
    "kaufen", "jetzt kaufen", "spenden", "zahlungspflichtig bestellen",
    "zahlung",
    # French
    "payer", "payer maintenant", "paiement", "proceder au paiement",
    "acheter", "acheter maintenant", "passer la commande",
    "commander et payer", "faire un don",
    # Spanish
    "pagar", "pagar ahora", "pago", "realizar el pedido",
    "finalizar compra", "comprar", "comprar ahora", "donar", "donacion",
    # Italian
    "paga", "paga ora", "pagare", "pagamento", "acquista", "acquistare",
    "acquista ora", "completa l ordine", "dona", "donazione",
    # Portuguese
    "finalizar compra", "finalizar pedido", "comprar agora", "doar",
    "doacao",
    # Korean
    "결제", "구매하기", "주문하기", "후원", "기부",
    # Japanese
    "支払", "購入", "決済", "注文確定", "寄付",
    # Chinese (simplified then traditional)
    "支付", "付款", "购买", "结算", "结账", "提交订单", "捐款", "捐赠",
    "購買", "結算", "結帳", "付費", "捐贈",
)

#: BARE CONFIRM terms. `Confirm`, `Continue` and `Complete` are the labels on
#: half the buttons on the web, so they fire only WITH a corroborating money
#: signal: a currency amount printed on the button itself, or an action path
#: that names a payment endpoint. Same multi-signal rule `BROADCAST_SEND`
#: follows, for the same reason.
PAYMENT_CONFIRM: tuple[str, ...] = (
    "confirm", "confirm and continue", "continue", "complete", "finish",
    "proceed", "submit", "order", "subscribe", "upgrade", "renew", "join",
    "bestatigen", "weiter", "fortfahren", "bestellen", "abschliessen",
    "confirmer", "continuer", "terminer", "commander",
    "confirmar", "continuar", "finalizar", "pedido", "suscribirse",
    "conferma", "continua", "completa", "ordine", "abbonarsi",
    "confirmar", "continuar", "concluir", "assinar",
    "확인", "계속", "완료", "주문", "구독",
    "確認", "続ける", "完了", "注文", "購読",
    "确认", "继续", "完成", "订单", "订阅", "確認", "繼續", "完成", "訂單",
)

#: Action paths that name a payment endpoint. Matched against the path only,
#: as the corroborating half of `PAYMENT_CONFIRM`. `order` and `cart` are
#: here and not in the strong table because a path is a weaker claim than a
#: label: `/orders` is as often the page that LISTS them.
PAYMENT_PATHS: tuple[str, ...] = (
    "pay", "payment", "payments", "checkout", "charge", "charges",
    "billing", "purchase", "order", "orders", "cart", "basket", "donate",
    "donation", "subscribe", "subscription", "stripe", "paypal",
    "braintree", "adyen", "kasse", "paiement", "pagar", "pago",
    "pagamento", "결제", "決済", "支付",
)

#: A price printed on the control. Run against the RAW text and never the
#: squashed haystack, because `squash` deletes every currency symbol on its
#: way to word boundaries: "Donate $50" reaches `matches()` as " donate 50 ".
_AMOUNT = re.compile(
    r"[$€£¥₩₹¢]\s?\d"
    r"|\d\s?[€£¥₩₹¢]"
    r"|\b(?:usd|eur|gbp|jpy|krw|cny|rmb|cad|aud|chf|inr|brl|mxn)\s?\d"
    r"|\d\s?(?:usd|eur|gbp|jpy|krw|cny|rmb|cad|aud|chf|inr|brl|mxn)\b"
    r"|\d\s?(?:원|円|元|€)",
    re.I | re.UNICODE)


def has_amount(*parts) -> bool:
    """True when a currency amount is printed on any of these raw strings."""
    raw = " ".join(str(p) for p in parts if p)[:400]
    return bool(_AMOUNT.search(raw))


#: Assent vocabulary that fires ANYWHERE, including on the submitter's own
#: name. Every entry is a phrase a page writes only when it means assent.
ASSENT_TERMS: tuple[str, ...] = (
    # English
    "i agree", "i accept", "i consent", "agree to the terms",
    "accept the terms", "terms of service", "terms and conditions",
    "privacy policy", "user agreement", "license agreement",
    "licence agreement", "eula",
    # German
    "ich stimme zu", "agb", "nutzungsbedingungen",
    "datenschutzerklarung", "einwilligung",
    # French
    "j accepte", "conditions generales", "conditions d utilisation",
    "politique de confidentialite",
    # Spanish
    "acepto", "terminos y condiciones", "terminos de servicio",
    "politica de privacidad",
    # Italian
    "accetto", "termini e condizioni", "informativa sulla privacy",
    # Portuguese
    "aceito", "termos e condicoes", "termos de servico",
    "politica de privacidade",
    # Korean
    "이용약관", "개인정보처리방침", "동의합니다",
    # Japanese
    "利用規約", "プライバシーポリシー", "同意します",
    # Chinese
    "服务条款", "隐私政策", "服務條款", "隱私政策",
)

#: Assent vocabulary that fires only on a form's CHECKBOX LABELS. These are
#: bare nouns a page writes beside a tickbox and also writes in a hundred
#: ordinary places, so the tickbox is the corroborating signal that makes
#: them a classification instead of a guess.
ASSENT_LABEL_TERMS: tuple[str, ...] = ASSENT_TERMS + (
    "agree", "accept", "terms", "conditions", "consent", "waiver",
    "zustimmen", "akzeptieren", "bedingungen",
    "accepter", "consentement",
    "aceptar", "consentimiento", "terminos",
    "accettare", "consenso", "termini",
    "aceitar", "termos",
    "동의", "약관",
    "同意", "規約",
    "条款", "條款",
)


# ------------------------------------------------------------ the classifier

def _submitter_hay(census: dict, names: tuple) -> str:
    return squash(census.get("submitter"), *names)


#: WHAT A SEARCH BOX IS, in the only vocabulary this module has to hand.
#: Matched against the form's action path and against the accessible names
#: of the control that was touched.
SEARCH_TERMS: tuple[str, ...] = (
    "search", "find", "lookup", "look up", "query", "browse",
    "suchen", "suche", "buscar", "busqueda", "rechercher", "recherche",
    "cerca", "ricerca", "pesquisar", "zoeken",
    "검색", "찾기", "検索", "搜索", "搜尋",
)


def _is_search_shaped(census: dict, path: str, names: tuple = ()) -> bool:
    """Is this the site's search box rather than its checkout?

    THE PORKBUN FALSE POSITIVE (live purchase field test, 2026-09-08). Their
    domain search form is a one-field GET that posts to `/checkout/search`,
    and `checkout` is in the strong payment vocabulary, so the path alone
    classified a search box as a payment form and the submit failed closed.
    On that site there was a URL-addressable search to fall back to; on a
    site without one it is a hard stop on a search box, and the `research`
    consent scope explicitly permits submitting query-shaped forms, so the
    classifier was overriding the exact case the scope carves out.

    EVERY CONDITION IS REQUIRED, and together they describe a form that
    cannot move money: one field, sent by GET, no payment field anywhere in
    it, no password or one-time code, and something in its path or in the
    control's own name that says search. A checkout form fails several of
    these at once -- it collects more than one field, it POSTs, and it
    carries a payment field -- so nothing that takes a payment can wear this
    exemption.

    It exempts ONLY the weak path signal. A one-field GET form whose button
    says "Pay now", or which prints a price, still classifies: what the
    control SAYS is a stronger claim than what the endpoint is called, and
    this narrows the weaker of the two."""
    if census.get("payment") or census.get("secret"):
        return False
    if str(census.get("method") or "GET").upper() != "GET":
        return False
    count = census.get("field_count")
    if not isinstance(count, int) or count != 1:
        return False
    if has_amount(census.get("submitter"), *names):
        return False
    if matches(squash(" ".join(str(n or "") for n in names)), SEARCH_TERMS):
        return True
    return bool(matches(path, SEARCH_TERMS))


def _payment_reason(census: dict, submitter: str, path: str,
                    names: tuple = ()) -> str | None:
    """Why this submission is a payment, or None.

    Three signals, and the corroboration rule is the one the rest of the
    module follows. The census flag is read FIRST and it was not read at
    all before: `ksFormPayment` computes it in the page and only
    `act.action_class_for` ever consulted it, so a census reaching this
    function through the delegate path carried the answer and nobody
    looked."""
    if census.get("payment"):
        return "the form carries a payment-shaped field"
    # THE SUBMITTER ROUTE IS ABSOLUTE. What the button says is the site
    # telling you what the button does, and no exemption below touches it.
    hit = matches(submitter, PAYMENT_TERMS)
    if hit:
        return f"the submission is named {hit!r}"
    # THE PATH ROUTE IS THE WEAKER CLAIM and it is the one a search box
    # trips: `/checkout/search` contains `checkout`. See `_is_search_shaped`.
    if not _is_search_shaped(census, path, names):
        hit = matches(path, PAYMENT_TERMS)
        if hit:
            return f"the submission is named {hit!r}"
    if has_amount(census.get("submitter"), *names):
        hit = matches(submitter, PAYMENT_CONFIRM) or \
            matches(path, PAYMENT_PATHS)
        if hit:
            return (f"the submission prints a price and is named {hit!r}")
    return None


def _action_hay(census: dict) -> str:
    """The form's action PATH, squashed. The host is deliberately excluded:
    a form posting to `deleteme.example.com/search` is a search on a
    badly-named host, and the path is where a site says what an endpoint
    does."""
    action = str(census.get("action") or "")
    action = action.split("?", 1)[0].split("#", 1)[0]
    if "://" in action:
        action = action.split("://", 1)[1]
        action = action[action.find("/"):] if "/" in action else ""
    return squash(action)


def classify(census: dict, *names) -> tuple[str, str] | None:
    """The finer submission class for a form send, with the reason, or None.

    `names` are the accessible names of the control that was touched and of
    the control the browser actually activates, so a delegated click cannot
    reach a class a direct click would miss and cannot skip one either.

    ORDER IS IRREVERSIBILITY, and it is the contract: money leaving is worse
    than a credential leaving, a credential leaving the machine is worse than
    a deletion, a deletion is worse than being bound by terms, and being
    bound by terms is worse than a post. A form that is several of these at
    once gates as the worst one and the prompt says which.

    Payment is first here because it is already first in
    `act.action_class_for`, which decides `payment_form` from the FIELDS
    before this function is ever called. This branch is the other half of
    that decision: the same class, reached from what the button says rather
    than from what the form collects."""
    if not isinstance(census, dict) or not census:
        return None

    submitter = _submitter_hay(census, names)
    path = _action_hay(census)

    payment = _payment_reason(census, submitter, path, names)
    if payment:
        return ("payment_form", payment)

    if census.get("secret"):
        return ("credential_submit",
                "the form carries a password or a one-time-code field")

    hit = matches(submitter, DESTRUCTIVE_TERMS) or \
        matches(path, DESTRUCTIVE_TERMS)
    if hit:
        return ("destructive_submit",
                f"the submission is named {hit!r}")

    labels = squash(census.get("checkbox_labels"))
    hit = matches(labels, ASSENT_LABEL_TERMS)
    if hit and census.get("submitter") is not None:
        return ("legal_assent",
                f"the form carries a checkbox labelled {hit!r}")
    hit = matches(submitter, ASSENT_TERMS)
    if hit:
        return ("legal_assent", f"the submission is named {hit!r}")

    textarea = bool(census.get("textarea"))
    recipient = bool(census.get("recipient"))
    hit = matches(submitter, BROADCAST_STRONG) or \
        matches(path, BROADCAST_STRONG)
    if hit:
        return ("broadcast_submit", f"the submission is named {hit!r}")
    if textarea and recipient:
        return ("broadcast_submit",
                "the form carries free text and a recipient field")
    if textarea or recipient:
        hit = matches(submitter, BROADCAST_SEND) or \
            matches(path, BROADCAST_SEND)
        if hit:
            return ("broadcast_submit",
                    f"the submission is named {hit!r} and the form carries "
                    f"free text or a recipient field")
    return None
