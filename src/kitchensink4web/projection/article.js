// KS4Web article extraction: the body kept, the chrome COUNTED, the refusal
// honest.
//
// The research found both incumbents refusing this on the record, so it is
// differentiation territory rather than catch-up, and the reason they refuse
// is worth stating: article extraction is a HEURISTIC, and a heuristic that
// cannot say "this is not an article" produces confident nonsense on the
// nine tenths of the web that is an application. So this file ships two
// things and the second is the load-bearing one: a Readability-class scorer,
// and a shape verdict that refuses rather than mangling.
//
// Implemented in-house against the machinery that is already here. There is
// no new dependency: the hidden-content rule is the SAME spliced
// `visibility.js` every other read uses (a `display:none` injection inside
// an article body is counted and withheld here exactly as it is in
// `get_text`), the block walk is `text.js`'s, and the instrument channel is
// the one the projection mints refs into.
//
// FOUR PROPERTIES, and the third is the one the brief asked for by name:
//
// 1. **Reading order, not DOM soup.** One depth-first walk emits headings,
//    paragraphs, list items, quotes, and code in the order a human reads
//    them, with tables named as tables and pointed at `get_table` rather
//    than flattened into prose.
// 2. **Links resolved.** An in-prose link arrives as `[text](/path)` with the
//    href resolved against the document, same-origin paths shortened the way
//    `get_links` shortens them. When the link markup would cost more than a
//    quarter of the body, it is dropped WHOLESALE and the drop is stated;
//    a body that is 40 percent bracket syntax is not a readable article.
// 3. **Boilerplate is EXCLUDED AND COUNTED, never silently dropped.** Every
//    block outside the article body is classified (nav, header, footer,
//    sidebar, comments, related, share, promo, form, other) and returned as
//    a per-reason tally of blocks and characters. A caller can always see
//    what the tool decided not to show it, which is the difference between
//    an extractor and a summarizer.
// 4. **A shape verdict.** An application page comes back `shape: "none"`
//    with the evidence that decided it, and the Python side turns that into
//    a refusal naming `get_page_view`. A thread-shaped page (a forum topic,
//    an issue, a comment stream) comes back `shape: "thread"` with its posts
//    and their authors and timestamps, because that shape rides this same
//    walk for the cost of one extra pass.
(opts) => {
// @@KS4WEB_INSTRUMENT@@
// @@KS4WEB_VISIBILITY@@
  const startIndex = Math.max(0, opts.start_index || 0);
  const maxChars = Math.max(200, Math.min(200000, opts.max_chars || 20000));
  const LINK_MODE = opts.links === 'none' ? 'none' : 'inline';

  const squash = (s) => (typeof s === 'string' ? s : '').replace(/\s+/g, ' ').trim();
  const clip = (s, n) => { s = squash(s); return s.length <= n ? s : s.slice(0, n) + '...'; };

  // The ONE hidden-content rule, spliced above. Copies drift; there is one
  // copy, and it is the same one the page view and the prose read consult.
  function hiddenReason(el) {
    const r = ksHiddenReason(el, null);
    if (r) return r;
    if (el.tagName === 'BODY' || !el.getBoundingClientRect) return null;
    return ksGeometryHidden(el, null).reason;
  }

  const BLOCK = new Set(['P', 'LI', 'BLOCKQUOTE', 'PRE', 'DD', 'DT',
    'FIGCAPTION', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6']);
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG',
    'IFRAME', 'OBJECT', 'CANVAS']);
  const ZERO_WIDTH = /[​-‏‪-‮⁠-⁤﻿]/g;

  // Readability's class weights, transcribed rather than invented: two
  // decades of pages have been tuned against these exact words and a fresh
  // guess would be a worse answer with more confidence.
  const POSITIVE = /article|body|content|entry|hentry|h-entry|main|page|post|story|text|blog|column|prose|markdown/i;
  const NEGATIVE = /combx|comment|contact|foot|footer|footnote|masthead|media|meta|outbrain|promo|related|recirc|scroll|shoutbox|sidebar|sponsor|shopping|tags|tool|widget|nav|menu|banner|social|share|breadcrumb|pagination|newsletter|subscribe|modal|popup|cookie|disqus|byline|utility|skip|hidden/i;

  function idclass(el) {
    return ((el.className && typeof el.className === 'string' ? el.className : '')
      + ' ' + (el.id || ''));
  }

  // ------------------------------------------------------------ scoring

  function linkDensity(el) {
    const total = squash(el.textContent || '').length;
    if (!total) return 1;
    let linked = 0;
    const anchors = el.querySelectorAll ? el.querySelectorAll('a[href]') : [];
    for (let i = 0; i < anchors.length; i++) {
      linked += squash(anchors[i].textContent || '').length;
    }
    return Math.min(1, linked / total);
  }

  function classWeight(el) {
    let weight = 0;
    const bag = idclass(el);
    if (bag) {
      if (NEGATIVE.test(bag)) weight -= 25;
      if (POSITIVE.test(bag)) weight += 25;
    }
    const tag = el.tagName;
    if (tag === 'ARTICLE') weight += 30;
    else if (tag === 'MAIN') weight += 25;
    else if (tag === 'SECTION') weight += 8;
    else if (tag === 'DIV') weight += 5;
    else if (tag === 'ASIDE' || tag === 'NAV' || tag === 'FOOTER'
             || tag === 'HEADER' || tag === 'FORM') weight -= 30;
    const role = el.getAttribute ? (el.getAttribute('role') || '') : '';
    if (role === 'main' || role === 'article') weight += 25;
    if (role === 'navigation' || role === 'banner' || role === 'contentinfo'
        || role === 'complementary' || role === 'search') weight -= 30;
    const itemprop = el.getAttribute ? (el.getAttribute('itemprop') || '') : '';
    if (/articlebody|articleBody/i.test(itemprop)) weight += 40;
    return weight;
  }

  // The scored pass. Every paragraph-shaped block donates its own weight to
  // its ancestors, full to the parent and falling off by depth, which is
  // what makes a container that holds twenty paragraphs beat one that holds
  // the single longest.
  const scores = new Map();
  const paraChars = new Map();
  let bodyProseChars = 0, bodyProseBlocks = 0;

  function addScore(el, amount, chars) {
    if (!el || el.nodeType !== 1 || el.tagName === 'BODY'
        || el.tagName === 'HTML') return;
    if (!scores.has(el)) scores.set(el, classWeight(el));
    scores.set(el, scores.get(el) + amount);
    paraChars.set(el, (paraChars.get(el) || 0) + chars);
  }

  const paragraphs = document.querySelectorAll('p, pre, blockquote, dd');
  for (let i = 0; i < paragraphs.length; i++) {
    const p = paragraphs[i];
    const text = squash(p.textContent || '');
    if (text.length < 25) continue;
    if (hiddenReason(p)) continue;
    bodyProseChars += text.length;
    bodyProseBlocks++;
    const commas = (text.match(/[,、，]/g) || []).length;
    const base = 1 + commas + Math.min(Math.floor(text.length / 100), 3);
    let node = p.parentElement;
    for (let depth = 0; node && depth < 5; depth++) {
      addScore(node, base / (depth + 1), text.length);
      node = node.parentElement;
    }
  }

  let best = null, bestScore = 0;
  scores.forEach((score, el) => {
    const adjusted = score * (1 - linkDensity(el));
    if (adjusted > bestScore) { bestScore = adjusted; best = el; }
  });

  // Climb one or two levels when the parent is nearly as good and holds
  // meaningfully more prose. Readability's sibling-merge step solves the same
  // problem (a body split across two divs) and this is the cheap half of it:
  // it never widens the selection to a container that is mostly chrome,
  // because the parent's own adjusted score is what gates the move.
  if (best) {
    for (let hop = 0; hop < 2; hop++) {
      const parent = best.parentElement;
      if (!parent || parent.tagName === 'BODY' || parent.tagName === 'HTML') break;
      const parentScore = (scores.get(parent) || 0) * (1 - linkDensity(parent));
      const gained = (paraChars.get(parent) || 0) - (paraChars.get(best) || 0);
      if (parentScore >= bestScore * 0.9 && gained > (paraChars.get(best) || 0) * 0.15) {
        best = parent; bestScore = parentScore;
      } else break;
    }
  }

  // A caller-named root SKIPS the scorer entirely. "Read this region as an
  // article" is a different question from "find the article on this page",
  // and answering the first by running the second would quietly relocate the
  // read somewhere the caller did not point at.
  let root, rootWas = 'auto';
  if (opts.root) {
    root = KS.refs.get(opts.root) || null;
    if (!root) return {error: 'ROOT_GONE', asked_for: opts.root};
    rootWas = opts.root;
  } else {
    root = best || document.body || document.documentElement;
  }

  // ---------------------------------------------------------- the walk

  const blocks = [];
  const hiddenReasons = {};
  let hiddenBlocks = 0, hiddenChars = 0, injectionSuspects = 0;
  let zeroWidth = 0, shadowRootsRead = 0;
  let linksResolved = 0, linkMarkupChars = 0, tablesSeen = 0;

  function resolveHref(a) {
    try {
      const u = new URL(a.href, location.href);
      return u.origin !== location.origin ? u.origin + u.pathname
        : (u.pathname + u.search + u.hash);
    } catch (e) { return a.getAttribute('href') || ''; }
  }

  // A block's own inline run, collected twice in ONE pass: `plain` is the
  // text, `rich` is the same text with in-prose links resolved. Both come
  // out of the same walk because the link-cost guard below has to compare
  // them, and walking twice to compare two walks is how they drift.
  function inlineText(el, plain, rich) {
    for (const node of el.childNodes) {
      if (node.nodeType === 3) {
        const v = node.nodeValue || '';
        plain.push(v); rich.push(v);
        continue;
      }
      if (node.nodeType !== 1) continue;
      if (SKIP.has(node.tagName) || BLOCK.has(node.tagName)) continue;
      if (hiddenReason(node)) continue;
      if (node.tagName === 'A' && node.hasAttribute('href')) {
        const inner = squash(node.textContent || '');
        const href = resolveHref(node);
        plain.push(' ' + inner + ' ');
        if (inner && href) {
          linksResolved++;
          const markup = '[' + inner + '](' + href + ')';
          linkMarkupChars += markup.length - inner.length;
          rich.push(' ' + markup + ' ');
        } else {
          rich.push(' ' + inner + ' ');
        }
        continue;
      }
      plain.push(' '); rich.push(' ');
      inlineText(node, plain, rich);
    }
  }

  function noteHidden(el, reason) {
    const text = squash(el.textContent || '');
    if (!text) return;
    hiddenBlocks++;
    hiddenChars += text.length;
    hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
    // The same rule `get_text` applies: a hidden block carrying real
    // sentences is the shape of a prompt injection. It is counted, named,
    // and never printed as article body.
    if (text.length > 20) injectionSuspects++;
  }

  // Ported from `text.js` rather than reinvented (gauntlet 2, L2): a
  // `visibility: hidden` block whose descendant sets `visibility: visible`
  // renders that descendant, and a walk that returns at the hidden ancestor
  // hands a page a reliable way to show a human something no tool reads. The
  // scan runs only when a visibility-hidden element is actually met.
  function hasVisibleDescendant(el) {
    if (!el.querySelectorAll) return false;
    const kids = el.querySelectorAll('*');
    for (let i = 0; i < kids.length && i < 500; i++) {
      if (ksCS(kids[i]).visibility === 'visible') return true;
    }
    return false;
  }

  (function walk(el) {
    if (SKIP.has(el.tagName)) return;
    const reason = hiddenReason(el);
    if (reason === 'visibility-hidden' && hasVisibleDescendant(el)) {
      // Count this element's OWN inline run as withheld, then keep going: the
      // recursion re-asks the question of every child, so one that inherits
      // `hidden` is counted in its turn and one that overrides it is read.
      const ownPlain = [], ownRich = [];
      inlineText(el, ownPlain, ownRich);
      const own = squash(ownPlain.join(''));
      if (own) {
        hiddenBlocks++;
        hiddenChars += own.length;
        hiddenReasons[reason] = (hiddenReasons[reason] || 0) + 1;
        if (own.length > 20) injectionSuspects++;
      }
      for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
        walk(child);
      }
      return;
    }
    if (reason) { noteHidden(el, reason); return; }

    if (el.tagName === 'TABLE') {
      const rows = el.rows ? el.rows.length : 0;
      const cols = (el.rows && el.rows[0]) ? el.rows[0].cells.length : 0;
      tablesSeen++;
      blocks.push({
        tag: 'table', ref: KS.refof.get(el) || null,
        text: '[table: ' + rows + ' row(s) x ' + cols
              + ' column(s). get_table reads it as JSON]',
        rich: null});
      return;
    }

    if (BLOCK.has(el.tagName)) {
      const plainParts = [], richParts = [];
      inlineText(el, plainParts, richParts);
      let plain = plainParts.join('');
      let rich = richParts.join('');
      // `replace` rather than `test`, because `test` on a /g/ regex carries
      // `lastIndex` between calls and the second block on the page would be
      // asked the question starting halfway through itself.
      const stripped = plain.replace(ZERO_WIDTH, '');
      if (stripped.length !== plain.length) {
        zeroWidth++;
        plain = stripped;
        rich = rich.replace(ZERO_WIDTH, '');
      }
      const text = squash(plain);
      if (text) {
        blocks.push({tag: el.tagName.toLowerCase(),
                     ref: KS.refof.get(el) || null,
                     text: text, rich: squash(rich)});
      }
    }
    for (let child = el.firstElementChild; child; child = child.nextElementSibling) {
      walk(child);
    }
    if (el.shadowRoot) {
      shadowRootsRead++;
      for (let child = el.shadowRoot.firstElementChild; child;
           child = child.nextElementSibling) {
        walk(child);
      }
    }
  })(root);

  // ------------------------------------------- boilerplate, excluded and COUNTED

  // Every prose block on the page that the article body did not claim, with
  // WHY it was not claimed. This is the accounting the brief asked for by
  // name: the exclusion is never silent, so a caller who thinks the tool cut
  // something can see the shape and the size of what it cut.
  const EXCLUSION_TESTS = [
    ['nav', 'nav, [role="navigation"], [role="menubar"], [role="tablist"]'],
    ['header', 'header, [role="banner"]'],
    ['footer', 'footer, [role="contentinfo"]'],
    ['sidebar', 'aside, [role="complementary"]'],
    ['form', 'form, [role="search"]'],
  ];
  const NAMED_PATTERNS = [
    ['comments', /comment|disqus|respond|discussion|replies/i],
    ['related', /related|recirc|recommend|more-from|read-next|readnext|trending|popular|also-like/i],
    ['share', /share|social|follow-us/i],
    // Ahead of nothing and behind `share` on purpose: a newsletter block is
    // a promotion, not a share widget, and putting `newsletter` in the share
    // pattern classified `promo-newsletter` as share on the first fixture
    // that carried one.
    ['promo', /promo|advert|\bads?\b|ad-|sponsor|paywall|upsell|banner|newsletter|subscribe/i],
  ];

  function exclusionReason(el) {
    for (let i = 0; i < EXCLUSION_TESTS.length; i++) {
      if (el.closest(EXCLUSION_TESTS[i][1])) return EXCLUSION_TESTS[i][0];
    }
    let node = el;
    for (let hop = 0; node && hop < 8; hop++) {
      const bag = idclass(node);
      if (bag) {
        for (let i = 0; i < NAMED_PATTERNS.length; i++) {
          if (NAMED_PATTERNS[i][1].test(bag)) return NAMED_PATTERNS[i][0];
        }
      }
      node = node.parentElement;
    }
    return 'other';
  }

  const excluded = {};
  let excludedBlocks = 0, excludedChars = 0;
  const pageBlocks = document.querySelectorAll(
    'p, li, blockquote, pre, dd, dt, figcaption, h1, h2, h3, h4, h5, h6');
  for (let i = 0; i < pageBlocks.length; i++) {
    const el = pageBlocks[i];
    if (root.contains(el)) continue;
    if (hiddenReason(el)) continue;           // already in the hidden ledger
    const text = squash(el.textContent || '');
    if (!text) continue;
    const reason = exclusionReason(el);
    if (!excluded[reason]) excluded[reason] = {blocks: 0, chars: 0};
    excluded[reason].blocks++;
    excluded[reason].chars += text.length;
    excludedBlocks++;
    excludedChars += text.length;
  }

  // --------------------------------------------------------- the metadata

  function metaContent(sel) {
    const el = document.querySelector(sel);
    if (!el) return null;
    const v = squash(el.getAttribute('content'));
    return v || null;
  }

  // JSON-LD, read only for the article types. A Website or Organization node
  // is not this page's byline and using it would be a confident wrong answer.
  const LD_TYPES = /^(Article|NewsArticle|BlogPosting|Report|ScholarlyArticle|TechArticle|LiveBlogPosting|DiscussionForumPosting|Posting|WebPage)$/i;
  let ld = null;
  const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (let i = 0; i < ldScripts.length && !ld; i++) {
    let parsed;
    try { parsed = JSON.parse(ldScripts[i].textContent); } catch (e) { continue; }
    const queue = Array.isArray(parsed) ? parsed.slice() : [parsed];
    while (queue.length && !ld) {
      const node = queue.shift();
      if (!node || typeof node !== 'object') continue;
      if (Array.isArray(node['@graph'])) {
        for (const sub of node['@graph']) queue.push(sub);
      }
      const types = [].concat(node['@type'] || []);
      for (const t of types) {
        if (typeof t === 'string' && LD_TYPES.test(t)) { ld = node; break; }
      }
    }
  }

  function ldPerson(value) {
    if (!value) return null;
    if (typeof value === 'string') return squash(value) || null;
    if (Array.isArray(value)) {
      const names = value.map(ldPerson).filter(Boolean);
      return names.length ? names.join(', ') : null;
    }
    if (typeof value === 'object' && value.name)
      return squash(String(value.name)) || null;
    return null;
  }

  // Each field states WHERE it came from. A byline that could be the page's
  // author or could be the site's owner is worth less than no byline, so the
  // source travels with the value and a field with no source is null rather
  // than a best guess.
  function pick(candidates) {
    for (let i = 0; i < candidates.length; i++) {
      const value = candidates[i][1];
      if (value) return {value: clip(String(value), 300), source: candidates[i][0]};
    }
    return {value: null, source: null};
  }

  const h1 = root.querySelector ? root.querySelector('h1') : null;
  const pageH1 = document.querySelector('h1');
  const title = pick([
    ['json-ld', ld ? (ld.headline || ld.name) : null],
    ['h1', h1 ? squash(h1.textContent) : null],
    ['og:title', metaContent('meta[property="og:title"]')],
    ['h1', pageH1 ? squash(pageH1.textContent) : null],
    ['document.title', squash(document.title)],
  ]);

  function domByline() {
    const sels = ['[itemprop="author"]', '[rel="author"]', 'a[rel~="author"]',
                  '.byline', '.author', '.post-author', '[class*="byline"]',
                  '[class*="author"]', '[data-testid*="author"]'];
    for (let i = 0; i < sels.length; i++) {
      let el = null;
      try { el = document.querySelector(sels[i]); } catch (e) { continue; }
      if (!el || hiddenReason(el)) continue;
      const text = squash(el.getAttribute('content') || el.textContent);
      // A byline is a name, not a paragraph. The length bound is what keeps
      // a `.author-bio` block from arriving as the byline.
      if (text && text.length <= 120) return text;
    }
    return null;
  }
  const byline = pick([
    ['json-ld', ld ? ldPerson(ld.author) : null],
    ['meta[name=author]', metaContent('meta[name="author"]')],
    ['markup', domByline()],
  ]);

  function timeEl(scope) {
    const el = scope.querySelector
      ? scope.querySelector('time[datetime], [itemprop="datePublished"][content], [datetime]')
      : null;
    if (!el) return null;
    return squash(el.getAttribute('datetime') || el.getAttribute('content')
                  || el.textContent) || null;
  }
  const published = pick([
    ['json-ld', ld ? (ld.datePublished || null) : null],
    ['meta[article:published_time]',
     metaContent('meta[property="article:published_time"]')],
    ['time[datetime]', timeEl(root)],
    ['meta[name=date]', metaContent('meta[name="date"]')],
    ['time[datetime]', timeEl(document)],
  ]);
  const modified = pick([
    ['json-ld', ld ? (ld.dateModified || null) : null],
    ['meta[article:modified_time]',
     metaContent('meta[property="article:modified_time"]')],
  ]);

  // ----------------------------------------------------- the shape verdict

  const articleChars = blocks.reduce((n, b) => n + b.text.length, 0);
  const proseBlocks = blocks.filter(
    (b) => b.tag === 'p' || b.tag === 'blockquote' || b.tag === 'pre').length;
  const rootDensity = linkDensity(root);
  // The denominator is the page's BLOCK-LEVEL prose, kept plus excluded, not
  // `body.textContent`. textContent counts script bodies and inline JSON as
  // page text, and on a heavy application shell that alone would make every
  // real article look like a rounding error against its own page.
  const pageChars = articleChars + excludedChars;

  // Four tests, each one a way a non-article fails. They are reported
  // individually rather than as a verdict, because "not article-shaped" with
  // no reason is the answer a caller cannot act on.
  const evidence = {
    prose_blocks: proseBlocks,
    article_chars: articleChars,
    link_density: Math.round(rootDensity * 100) / 100,
    share_of_page: pageChars ? Math.round((articleChars / pageChars) * 100) / 100 : 0,
    page_chars: pageChars,
  };
  const failed = [];
  if (proseBlocks < 3) failed.push('fewer than 3 paragraph-shaped blocks');
  if (articleChars < 400) failed.push('under 400 characters of body prose');
  if (rootDensity > 0.5) failed.push('over half the body text is link text');
  if (pageChars && articleChars / pageChars < 0.15)
    failed.push('the body holds under 15 percent of the page text');

  // ------------------------------------------------------ the thread shape

  // The research's issue/blog/forum ask. It rides this same walk: a thread is
  // repeated sibling containers each carrying a machine-readable timestamp,
  // which is the one structural signal every forum, issue tracker, and
  // comment stream actually ships. Nothing here guesses: no timestamps, no
  // thread, and the tool says so rather than inventing a post list.
  function detectThread() {
    const stamps = document.querySelectorAll('time[datetime], [datetime]');
    if (stamps.length < 3) return null;
    const groups = new Map();
    for (let i = 0; i < stamps.length; i++) {
      const stamp = stamps[i];
      if (hiddenReason(stamp)) continue;
      let node = stamp;
      for (let hop = 0; hop < 8 && node && node.parentElement; hop++) {
        const parent = node.parentElement;
        if (parent === document.body || parent.tagName === 'HTML') break;
        let siblingsWithStamps = 0;
        for (let c = parent.firstElementChild; c; c = c.nextElementSibling) {
          if (c.querySelector && (c.querySelector('time[datetime], [datetime]')
              || (c.matches && c.matches('time[datetime], [datetime]'))))
            siblingsWithStamps++;
        }
        if (siblingsWithStamps >= 3) {
          if (!groups.has(parent)) groups.set(parent, []);
          const seen = groups.get(parent);
          if (seen.indexOf(node) < 0) seen.push(node);
          break;
        }
        node = parent;
      }
    }
    let container = null, posts = null;
    groups.forEach((members, parent) => {
      if (!posts || members.length > posts.length) {
        container = parent; posts = members;
      }
    });
    if (!container || !posts || posts.length < 3) return null;

    const AUTHOR_SEL = '[itemprop="author"], [rel="author"], a[rel~="author"], '
      + '.author, .username, .user, [class*="author"], [class*="username"], '
      + '[data-testid*="author"], h3 a, h4 a';
    const out = [];
    let totalChars = 0;
    for (let i = 0; i < posts.length && i < 200; i++) {
      const post = posts[i];
      if (hiddenReason(post)) continue;
      const stamp = post.matches && post.matches('time[datetime], [datetime]')
        ? post : post.querySelector('time[datetime], [datetime]');
      let author = null;
      try {
        const a = post.querySelector(AUTHOR_SEL);
        if (a) {
          const text = squash(a.getAttribute('content') || a.textContent);
          if (text && text.length <= 120) author = text;
        }
      } catch (e) { /* selector unsupported here; author stays null */ }
      const body = squash(post.textContent || '');
      totalChars += body.length;
      out.push({
        index: i,
        ref: KS.refof.get(post) || null,
        author: author,
        timestamp: stamp ? squash(stamp.getAttribute('datetime')
                                  || stamp.getAttribute('content') || '') || null : null,
        timestamp_text: stamp ? clip(stamp.textContent, 60) || null : null,
        text: clip(body, 1200),
      });
    }
    if (out.length < 3 || totalChars < 200) return null;
    return {
      posts: out,
      total_posts: out.length,
      with_author: out.filter((p) => p.author).length,
      with_timestamp: out.filter((p) => p.timestamp).length,
      chars: totalChars,
    };
  }

  const thread = failed.length ? detectThread() : null;
  const shape = !failed.length ? 'article' : (thread ? 'thread' : 'none');

  // ----------------------------------------------------------- the payload

  // LINKS. The resolved form is the default and it is what makes the body
  // useful, but a body that is a quarter bracket syntax is not readable, so
  // the guard drops the markup WHOLESALE and says it did. Half-linked prose
  // would be the worst of both.
  const plainBody = blocks.map((b) => (/^h[1-6]$/.test(b.tag)
    ? '\n' + b.text + '\n' : b.text)).join('\n');
  let linksDropped = false;
  let body = plainBody;
  if (LINK_MODE === 'inline' && linksResolved) {
    if (plainBody.length && linkMarkupChars / plainBody.length > 0.25) {
      linksDropped = true;
    } else {
      body = blocks.map((b) => {
        const t = b.rich === null ? b.text : b.rich;
        return /^h[1-6]$/.test(b.tag) ? '\n' + t + '\n' : t;
      }).join('\n');
    }
  }

  const slice = body.slice(startIndex, startIndex + maxChars);
  const nextIndex = startIndex + slice.length;

  return {
    shape: shape,
    root: rootWas,
    url: location.href,
    lang: document.documentElement.getAttribute('lang') || null,
    site_name: metaContent('meta[property="og:site_name"]'),
    title: title, byline: byline, published: published, modified: modified,
    text: shape === 'none' ? '' : slice,
    start_index: startIndex,
    next_start_index: (shape !== 'none' && nextIndex < body.length)
      ? nextIndex : null,
    total_chars: body.length,
    returned_chars: shape === 'none' ? 0 : slice.length,
    blocks: blocks.length,
    tables: tablesSeen,
    thread: thread,
    links: {
      mode: LINK_MODE,
      resolved: linksResolved,
      dropped: linksDropped,
      markup_chars: linkMarkupChars,
    },
    excluded: {
      blocks: excludedBlocks, chars: excludedChars, by_reason: excluded,
    },
    hidden: {
      blocks: hiddenBlocks, chars: hiddenChars, reasons: hiddenReasons,
      injection_suspects: injectionSuspects, zero_width_blocks: zeroWidth,
    },
    shadow_roots_read: shadowRootsRead,
    closed_shadow_roots: (KS.closed || 0),
    evidence: evidence,
    failed_tests: failed,
  };
}
