"""The submission classifier: which KIND of consequential thing a form send is.

DESIGN 5.4a. `form_submit` used to cover "run this search" and "delete my
account" with one class, one prompt, and one sentence, which is the whole of
the author's complaint: the gate could not name its own harm, so it fired on
research and taught people to click through prompts. This module splits the
class into the four that CAN name their harm, and the residual keeps the old
name.

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

    ORDER IS IRREVERSIBILITY, and it is the contract: a credential leaving
    the machine is worse than a deletion, a deletion is worse than being
    bound by terms, and being bound by terms is worse than a post. A form
    that is several of these at once gates as the worst one and the prompt
    says which."""
    if not isinstance(census, dict) or not census:
        return None
    if census.get("secret"):
        return ("credential_submit",
                "the form carries a password or a one-time-code field")

    submitter = _submitter_hay(census, names)
    path = _action_hay(census)

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
