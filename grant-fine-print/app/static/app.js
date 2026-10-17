/* Grant Fine Print — Client Interactions
 * "The fine print, under a magnifier."
 */

(function () {
  "use strict";

  // 1. Dark Mode / Warm Paper Theme Toggle
  function initTheme() {
    const saved = localStorage.getItem("gfp_theme");
    if (saved === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }

    const toggleBtn = document.getElementById("theme-toggle");
    if (toggleBtn) {
      updateThemeButtonText(toggleBtn);
      toggleBtn.addEventListener("click", function () {
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        if (isDark) {
          document.documentElement.removeAttribute("data-theme");
          localStorage.setItem("gfp_theme", "light");
        } else {
          document.documentElement.setAttribute("data-theme", "dark");
          localStorage.setItem("gfp_theme", "dark");
        }
        updateThemeButtonText(toggleBtn);
      });
    }
  }

  function updateThemeButtonText(btn) {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    btn.innerHTML = isDark ? "☼ Paper mode" : "☾ Dark ink";
  }

  // 2. Mobile Nav Toggle
  function initMobileNav() {
    const toggle = document.querySelector(".menu-toggle");
    const header = document.getElementById("site-header");
    if (!toggle || !header) return;
    toggle.addEventListener("click", function () {
      const open = header.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Close" : "Menu";
    });
  }

  // 3. Count-up Animation for Hero Strip
  function initCountUp() {
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    const countEls = document.querySelectorAll(".count-up");
    countEls.forEach(function (el) {
      const target = parseInt(el.getAttribute("data-target"), 10);
      if (isNaN(target) || target <= 0) return;

      const duration = 1200;
      const startTime = performance.now();

      function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Easing out cubic
        const ease = 1 - Math.pow(1 - progress, 3);
        const current = Math.floor(ease * target);
        el.textContent = current.toLocaleString();

        if (progress < 1) {
          requestAnimationFrame(update);
        } else {
          el.textContent = target.toLocaleString();
        }
      }

      requestAnimationFrame(update);
    });
  }

  // 4. Client-side SVG to PNG Exporter for Evidence Charts
  window.downloadSvgAsPng = function (svgId, filename) {
    const svg = document.getElementById(svgId);
    if (!svg) {
      alert("Chart SVG not found.");
      return;
    }

    const svgData = new XMLSerializer().serializeToString(svg);
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const img = new Image();

    // Use current theme paper background
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    const bgColor = isDark ? "#1D1812" : "#F4EFE3";

    const svgBlob = new Blob([svgData], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);

    img.onload = function () {
      const width = (svg.clientWidth || 800) * 2;
      const height = (svg.clientHeight || 400) * 2;
      canvas.width = width;
      canvas.height = height;

      ctx.fillStyle = bgColor;
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(url);

      const a = document.createElement("a");
      a.download = (filename || "grant-fine-print-evidence") + ".png";
      a.href = canvas.toDataURL("image/png");
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    };

    img.src = url;
  };

  // 5. Inline Correction Drawer Toggle
  window.toggleCorrectionDrawer = function (oppId) {
    const drawer = document.getElementById("corr-" + oppId);
    if (drawer) {
      drawer.hidden = !drawer.hidden;
      if (!drawer.hidden) {
        const input = drawer.querySelector("select, textarea");
        if (input) input.focus();
      }
  };

  // 5b. 'This is wrong' handler per card with small confirmation
  window.flagWrong = function (oppId) {
    if (confirm("Flag opportunity " + oppId + " as having an incorrect verdict or fine-print quote?")) {
      const oppInput = document.getElementById("corr-opp-id");
      const box = document.getElementById("record-correction-box");
      if (oppInput && box) {
        oppInput.value = oppId;
        box.scrollIntoView({ behavior: "smooth" });
        const noteInput = document.getElementById("corr-note");
        if (noteInput) noteInput.focus();
      }
    }
  };

  // 6. SerpApi Quick Discover via POST /discover/<opp_id>
  window.discoverOfficialLink = function (oppId, btnEl) {
    if (!btnEl) return;
    const origText = btnEl.textContent;
    btnEl.textContent = "Searching Grants.gov...";
    btnEl.disabled = true;

    fetch("/discover/" + encodeURIComponent(oppId), {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (data.status === "ok" && data.link) {
          btnEl.outerHTML = '<a class="card-link-btn" href="' + encodeURI(data.link) + '" target="_blank" rel="noopener">Official notice &rarr;</a>';
        } else {
          btnEl.textContent = "Not found on Grants.gov";
          setTimeout(function () {
            btnEl.textContent = origText;
            btnEl.disabled = false;
          }, 3000);
        }
      })
      .catch(function () {
        btnEl.textContent = "Search error";
        setTimeout(function () {
          btnEl.textContent = origText;
          btnEl.disabled = false;
        }, 3000);
      });
  };

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initTheme();
      initMobileNav();
      initCountUp();
    });
  } else {
    initTheme();
    initMobileNav();
    initCountUp();
  }
})();
