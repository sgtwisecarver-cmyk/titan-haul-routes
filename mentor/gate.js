/* Titan Mentor Qualification — access gate + draft banner + noindex
 * Same pattern as the Tank Board: CLIENT-SIDE ONLY. The password is hashed (SHA-256) and compared in the
 * browser, and the page content is already downloaded. This deters casual visitors; it is not security.
 *
 * To make a page PUBLIC (e.g. pull the overview out later), add its filename to PUBLIC below. One line.
 */
(function(){
  var PUBLIC = [];                                   // e.g. ['index.html'] to un-gate the overview
  var KEY  = 'titan_mentor_ok';
  var HASH = 'c4564a6d0ba49b003c456f8783d24a061c5ee7248e587c589b4414fd74c60e21';   // sha256('TitanMentor')

  var page = (location.pathname.split('/').pop() || 'index.html').toLowerCase();

  // ---- noindex on every page in this section (belt; robots.txt is braces) ----
  var m = document.createElement('meta'); m.name = 'robots'; m.content = 'noindex, nofollow, noarchive'; document.head.appendChild(m);

  // ---- shared styles ----
  var css = document.createElement('style');
  css.textContent =
    '#tmg{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;padding:18px;' +
      'background:linear-gradient(160deg,#0d1338 0%,#141c52 55%,#1e2a78 100%);font-family:"Inter","Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#e8eaef}' +
    '#tmg .box{width:100%;max-width:360px;text-align:center}' +
    '#tmg .logo{display:inline-flex;background:#fff;border-radius:10px;padding:10px 18px;margin-bottom:14px;box-shadow:0 4px 18px rgba(0,0,0,.45)}' +
    '#tmg .logo img{display:block;height:56px;width:auto}' +
    '#tmg .t{font-family:"Barlow Condensed","Arial Narrow","Segoe UI",sans-serif;font-weight:700;font-size:26px;letter-spacing:2px;text-transform:uppercase;line-height:1.05;margin:2px 0 4px}' +
    '#tmg .s{color:#7fd2f5;font-family:"Barlow Condensed","Arial Narrow","Segoe UI",sans-serif;font-size:13px;letter-spacing:2.6px;text-transform:uppercase;margin-bottom:20px}' +
    '#tmg .lbl{color:#c9ced8;font-size:14px;margin-bottom:8px}' +
    '#tmg input{width:100%;box-sizing:border-box;padding:14px;border-radius:10px;border:1px solid #3a3f4b;background:#141c52;color:#fff;font-size:18px;text-align:center;letter-spacing:2px}' +
    '#tmg button{width:100%;margin-top:12px;padding:14px;border:0;border-radius:10px;background:linear-gradient(180deg,#2a3a9e,#1e2a78);color:#fff;font-weight:800;font-size:16px;cursor:pointer}' +
    '#tmg .err{color:#ff8a8a;font-size:13px;height:18px;margin-top:10px}' +
    '#tmg .back{display:block;margin-top:18px;color:#7fd2f5;text-decoration:none;font-weight:700;font-size:13px}' +
    '#tmg .draft{margin-top:22px;font-size:12px;color:#c9ced8;opacity:.8}' +
    '#tmdraft{position:sticky;top:0;z-index:9999;background:#f5a623;color:#1b1400;font-family:"Inter","Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-weight:800;font-size:13px;letter-spacing:.4px;text-align:center;padding:8px 12px;border-bottom:2px solid #a8701a}' +
    '#tmdraft a{color:#1b1400;text-decoration:underline;font-weight:700;margin-left:10px}' +
    'html.tm-locked body>*:not(#tmg){visibility:hidden}';
  document.head.appendChild(css);

  // ---- draft banner on every page (visible even when unlocked) ----
  function banner(){
    if (document.getElementById('tmdraft')) return;
    var b = document.createElement('div'); b.id = 'tmdraft';
    b.innerHTML = '&#9888;&#65039; DRAFT &mdash; Mentor Qualification program mockup for leadership review. Not published policy.' +
                  '<a href="../index.html">&larr; Haul Routes</a>';
    document.body.insertBefore(b, document.body.firstChild);
  }

  function unlocked(){ try { return sessionStorage.getItem(KEY) === '1'; } catch(e){ return false; } }
  function setUnlocked(){ try { sessionStorage.setItem(KEY, '1'); } catch(e){} }

  function sha256(str){
    var enc = new TextEncoder().encode(str);
    return crypto.subtle.digest('SHA-256', enc).then(function(buf){
      return Array.prototype.map.call(new Uint8Array(buf), function(b){ return ('0'+b.toString(16)).slice(-2); }).join('');
    });
  }

  function showGate(){
    document.documentElement.classList.add('tm-locked');
    var g = document.createElement('div'); g.id = 'tmg';
    g.innerHTML =
      '<div class="box">' +
        '<div class="logo"><img src="../img/titan-logo.png" alt="Titan Energy Transportation"></div>' +
        '<div class="t">Mentor Qualification</div>' +
        '<div class="s">Titan EHS &middot; Train-the-Trainer</div>' +
        '<div class="lbl">Enter passcode</div>' +
        '<input id="tmpc" type="password" inputmode="text" autocomplete="off" autocapitalize="none" autofocus>' +
        '<button id="tmgo" type="button">Unlock</button>' +
        '<div class="err" id="tmerr"></div>' +
        '<a class="back" href="../index.html">&larr; Back to Haul Routes</a>' +
        '<div class="draft">DRAFT &mdash; not published policy. For leadership review.</div>' +
      '</div>';
    document.body.appendChild(g);
    var inp = document.getElementById('tmpc'), err = document.getElementById('tmerr');
    function attempt(){
      var v = (inp.value || '').trim();
      if (!v) return;
      if (!window.crypto || !crypto.subtle) { err.textContent = 'This browser cannot unlock — try Chrome or Safari.'; return; }
      sha256(v).then(function(h){
        if (h === HASH) { setUnlocked(); g.remove(); document.documentElement.classList.remove('tm-locked'); banner(); }
        else { err.textContent = 'Incorrect passcode.'; inp.value = ''; inp.focus(); }
      });
    }
    document.getElementById('tmgo').addEventListener('click', attempt);
    inp.addEventListener('keydown', function(e){ if (e.key === 'Enter') attempt(); });
    setTimeout(function(){ inp.focus(); }, 50);
  }

  // decide immediately (script runs from <head>) so gated content never paints before the overlay
  var needGate = !(PUBLIC.indexOf(page) >= 0 || unlocked());
  if (needGate) document.documentElement.classList.add('tm-locked');
  function init(){ if (needGate) showGate(); else banner(); }
  if (document.body) init(); else document.addEventListener('DOMContentLoaded', init);
})();
