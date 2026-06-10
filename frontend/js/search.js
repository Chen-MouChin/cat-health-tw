(function () {
  'use strict';

  var SUGGESTIONS = [
    // 醫療
    '腎衰竭', '慢性腎病 CKD', '貓咪糖尿病', '甲狀腺機能亢進', '心臟病',
    '胰臟炎', '脂肪肝', '泌尿道感染', '膀胱炎', '毛球症',
    '皮膚過敏', '嘔吐原因', '腹瀉原因', '貓咪發燒', '結石',
    '貓愛滋 FIV', '貓白血病 FeLV', '貓傳腹 FIP',
    // 預防
    '疫苗時程', '結紮手術', '定期健檢',
    // 飲食
    '乾糧選擇', '濕食推薦', '生食 BARF', '幼貓飲食', '老貓飲食',
    '腎病飲食', '水分攝取', '貓咪毒食物',
    // 行為
    '貓咪攻擊行為', '貓咪焦慮', '貓咪噴尿', '磨爪行為',
    '貓咪不吃東西', '貓咪夜間嚎叫',
    // 生命週期
    '幼貓照護', '老貓照護', '幼貓社會化', '貓咪壽命',
    // 品種
    '波斯貓', '美國短毛貓', '蘇格蘭摺耳貓', '緬因貓', '布偶貓',
    '英國短毛貓', '孟加拉貓', '暹羅貓', '阿比西尼亞貓', '俄羅斯藍貓',
    // 居家
    '貓砂選擇', '貓咪環境豐富化', '室內貓', '貓抓板',
    // 法規與領養
    '晶片登記', '寵物法規', '台灣領養貓咪',
  ];

  const MEDICAL_TERMS = [
    '腎衰', 'CKD', '慢性腎病', '糖尿病', '甲狀腺', '心臟病', '腫瘤', '癌',
    '感染', '疫苗', '骨折', '跛行', '嘔吐', '腹瀉', '便秘', '發燒',
    '過敏', '皮膚病', '泌尿', '結石', '脂肪肝', '貧血', '白血病', '胰臟炎'
  ];

  const CAT_EMOJI = {
    飲食: '🍖', 醫療: '🏥', 行為: '🧠', 居家環境: '🏠',
    生命週期: '📅', 品種: '🐱', 法規: '⚖️', 領養: '🏡'
  };

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function highlight(text, terms) {
    let out = escapeHtml(text);
    for (const term of terms) {
      const esc = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      out = out.replace(new RegExp(esc, 'g'), '<mark>' + term + '</mark>');
    }
    return out;
  }

  function scoreArticle(article, terms) {
    let score = 0;
    for (const term of terms) {
      if (article.title.includes(term)) score += 10;
      if (Array.isArray(article.tags) && article.tags.some(function(t){ return t.includes(term); })) score += 5;
      if (article.description.includes(term)) score += 3;
      if ((article.body_text || '').includes(term)) score += 1;
    }
    return score;
  }

  function isMedical(terms) {
    return terms.some(t =>
      MEDICAL_TERMS.some(m => m.includes(t) || t.includes(m))
    );
  }

  function renderArticleCard(a, terms, query) {
    const emoji = CAT_EMOJI[a.category] || '📖';
    const thumbSrc = a.cover_image
      ? (a.cover_image.startsWith('http') ? a.cover_image : '../' + a.cover_image)
      : '';
    const thumbHtml = thumbSrc
      ? '<img class="article-card-thumb" src="' + thumbSrc + '" alt="' + escapeHtml(a.title) + '" loading="lazy">'
      : '<div class="article-card-thumb" style="display:flex;align-items:center;justify-content:center;font-size:2rem">' + emoji + '</div>';
    const url = 'articles/' + a.slug + '.html?q=' + encodeURIComponent(query);
    return '<a class="article-card" href="' + url + '">\n'
      + '  ' + thumbHtml + '\n'
      + '  <div class="article-card-body">\n'
      + '    <div class="meta"><span class="cat-badge">' + emoji + ' ' + escapeHtml(a.category) + '</span><span>📅 ' + escapeHtml(a.date) + '</span></div>\n'
      + '    <h2>' + highlight(a.title, terms) + '</h2>\n'
      + '    <p>' + highlight(a.description.slice(0, 120), terms) + '</p>\n'
      + '  </div>\n'
      + '</a>';
  }

  function renderVetCard(vet) {
    var mapsUrl = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent((vet.name || '') + ' ' + (vet.address || ''));
    return '<a class="vet-card" href="' + mapsUrl + '" target="_blank" rel="noopener">'
      + '<strong>' + escapeHtml(vet.name) + '</strong>'
      + '<div class="vet-meta">📍 ' + escapeHtml((vet.city || '') + ' ' + (vet.district || '')) + ' &nbsp;·&nbsp; 📞 ' + escapeHtml(vet.tel || '—') + '</div>'
      + '<div class="vet-addr">' + escapeHtml(vet.address || '') + '</div>'
      + (vet.business_hours ? '<div class="vet-hours">⏰ ' + escapeHtml(vet.business_hours) + '</div>' : '')
      + '</a>';
  }

  function normalizeQuery(q) {
    return q
      .replace(/[\u3001\uff0c,\/|+&·\u00b7\u30fb\u2022\uff5c\uff01\uff1f]/g, ' ') // 、，,/|+&·・•｜！？ → space
      .replace(/\s+/g, ' ')   // collapse multiple spaces (includes full-width \u3000)
      .trim();
  }

  function highlightSuggest(text, query) {
    // Highlight matching part in suggestion item (no HTML escape needed — text is from static array)
    var esc = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return text.replace(new RegExp(esc, 'g'), '<mark>$&</mark>');
  }

  function initAutocomplete(inputEl, formEl) {
    var listEl = document.getElementById('suggestList');
    if (!listEl) return;
    var activeIdx = -1;

    function showSuggestions(matches) {
      if (matches.length === 0) { listEl.style.display = 'none'; return; }
      activeIdx = -1;
      listEl.innerHTML = matches.map(function (item) {
        return '<div class="suggest-item" data-val="' + escapeHtml(item) + '">'
          + highlightSuggest(escapeHtml(item), inputEl.value.trim())
          + '</div>';
      }).join('');
      listEl.style.display = 'block';
      listEl.querySelectorAll('.suggest-item').forEach(function (el) {
        el.addEventListener('mousedown', function (e) {
          e.preventDefault(); // prevent blur before click registers
          inputEl.value = this.getAttribute('data-val');
          listEl.style.display = 'none';
          formEl.submit();
        });
      });
    }

    function setActive(items, idx) {
      items.forEach(function (el, i) { el.classList.toggle('active', i === idx); });
    }

    inputEl.addEventListener('input', function () {
      var val = normalizeQuery(this.value);
      if (!val) { listEl.style.display = 'none'; return; }
      // For autocomplete, match the last token (user may have typed multiple words)
      var lastTerm = val.split(' ').pop();
      var matches = SUGGESTIONS.filter(function (s) { return s.includes(lastTerm); }).slice(0, 8);
      showSuggestions(matches);
    });

    inputEl.addEventListener('keydown', function (e) {
      var items = listEl.querySelectorAll('.suggest-item');
      if (listEl.style.display === 'none' || items.length === 0) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeIdx = Math.min(activeIdx + 1, items.length - 1);
        setActive(items, activeIdx);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeIdx = Math.max(activeIdx - 1, 0);
        setActive(items, activeIdx);
      } else if (e.key === 'Enter' && activeIdx >= 0) {
        e.preventDefault();
        inputEl.value = items[activeIdx].getAttribute('data-val');
        listEl.style.display = 'none';
        formEl.submit();
      } else if (e.key === 'Escape') {
        listEl.style.display = 'none';
        activeIdx = -1;
      }
    });

    inputEl.addEventListener('blur', function () {
      setTimeout(function () { listEl.style.display = 'none'; }, 150);
    });
  }

  function init() {
    const params = new URLSearchParams(location.search);
    const query = normalizeQuery(params.get('q') || '');
    const searchInput = document.getElementById('searchInput');
    const resultTitle = document.getElementById('resultTitle');
    const resultsEl = document.getElementById('searchResults');
    const vetSection = document.getElementById('vetSection');

    if (searchInput) searchInput.value = query;
    var searchForm = document.getElementById('searchForm');
    if (searchInput && searchForm) initAutocomplete(searchInput, searchForm);

    if (!query) {
      if (resultTitle) resultTitle.textContent = '請輸入關鍵字搜尋';
      return;
    }

    const terms = query.split(/\s+/).filter(Boolean);

    if (!window.ARTICLES_INDEX) {
      if (resultTitle) resultTitle.textContent = '搜尋索引載入失敗，請重新整理。';
      return;
    }

    const scored = window.ARTICLES_INDEX
      .map(function (a) { return { a: a, score: scoreArticle(a, terms) }; })
      .filter(function (x) { return x.score > 0; })
      .sort(function (x, y) { return y.score - x.score; })
      .slice(0, 20);

    if (resultTitle) {
      resultTitle.textContent = '「' + query + '」共找到 ' + scored.length + ' 篇相關文章';
    }

    if (resultsEl) {
      if (scored.length === 0) {
        resultsEl.innerHTML = '<p class="no-results">找不到相關文章，試試其他關鍵字。</p>';
      } else {
        resultsEl.innerHTML = scored.map(function (x) {
          return renderArticleCard(x.a, terms, query);
        }).join('\n');
      }
    }

    if (vetSection && isMedical(terms)) {
      vetSection.style.display = 'block';
      const vetList = vetSection.querySelector('#vetList');
      fetch('data/vets.json')
        .then(function (r) { return r.json(); })
        .then(function (vets) {
          if (vetList) vetList.innerHTML = vets.slice(0, 5).map(renderVetCard).join('');
        })
        .catch(function () {
          if (vetList) vetList.innerHTML = '<p style="color:var(--text-muted,#888)">獸醫資源暫時無法載入。</p>';
        });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
