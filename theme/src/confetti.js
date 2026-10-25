
(function () {
  // ── Self-contained confetti (no CDN, no workers — CSP safe) ──────────
  function launchConfetti() {
    var canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:99999;';
    document.body.appendChild(canvas);
    var ctx = canvas.getContext('2d');
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;

    var colors = ['#c8b8ff','#ffd6a5','#a0e8ff','#ffffff','#ff9de2'];
    var pieces = [];
    for (var i = 0; i < 180; i++) {
      pieces.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height - canvas.height,
        w: (Math.random() * 10) + 6,
        h: (Math.random() * 6) + 4,
        color: colors[Math.floor(Math.random() * colors.length)],
        rot: Math.random() * Math.PI * 2,
        vx: (Math.random() - 0.5) * 3,
        vy: (Math.random() * 4) + 3,
        vr: (Math.random() - 0.5) * 0.2
      });
    }

    var start = null;
    var duration = 3500;

    function draw(ts) {
      if (!start) start = ts;
      var elapsed = ts - start;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      var alive = false;
      pieces.forEach(function (p) {
        p.x  += p.vx;
        p.y  += p.vy;
        p.rot += p.vr;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = elapsed < duration ? Math.max(0, 1 - (elapsed / duration) * 0.5) : 0;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
        if (p.y < canvas.height + 20) alive = true;
      });
      if (alive && elapsed < duration + 1000) {
        requestAnimationFrame(draw);
      } else {
        canvas.remove();
      }
    }
    requestAnimationFrame(draw);
  }

  // ── Watch native Ghost subscribe form for success class ──────────────
  function watchForms() {
    document.querySelectorAll('[data-members-form]').forEach(function (form) {
      if (form.__confettiWatched) return;
      form.__confettiWatched = true;
      new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
          if (m.attributeName === 'class' && m.target.classList.contains('success')) {
            launchConfetti();
          }
        });
      }).observe(form, { attributes: true });
    });

    // Ghost Portal popup signups
    window.addEventListener('ghost:portal:action', function (e) {
      var action = e && e.detail && e.detail.action;
      if (action === 'signup' || action === 'checkout.complete') {
        launchConfetti();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watchForms);
  } else {
    watchForms();
  }
})();
