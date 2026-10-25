/* MultimediaHub — progressive enhancement. The site works without this file. */
(function () {
  "use strict";

  // ---- Mobile navigation ----
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });
  }

  // ---- Dismissible messages ----
  document.querySelectorAll(".message-close").forEach(function (button) {
    button.addEventListener("click", function () {
      var message = button.closest(".message");
      if (message) { message.remove(); }
    });
  });

  // ---- Confirmation prompts (forms with data-confirm) ----
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  });

  // ---- Loading state on submit (forms with data-loading-text) ----
  document.querySelectorAll("form[data-loading-text]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) { return; }
      var button = form.querySelector('button[type="submit"]');
      if (button && !button.disabled) {
        // Defer so the form data is still submitted before the button is disabled.
        window.setTimeout(function () {
          button.disabled = true;
          button.classList.add("is-loading");
          button.textContent = form.getAttribute("data-loading-text");
        }, 0);
      }
    });
  });

  // ---- Character counters for textareas with maxlength ----
  document.querySelectorAll("textarea[maxlength]").forEach(function (area) {
    var counter = document.createElement("p");
    counter.className = "char-count";
    counter.setAttribute("aria-live", "polite");
    area.insertAdjacentElement("afterend", counter);
    var max = parseInt(area.getAttribute("maxlength"), 10);
    function update() { counter.textContent = area.value.length + " / " + max; }
    area.addEventListener("input", update);
    update();
  });

  // ---- File selection preview ----
  function formatSize(bytes) {
    if (bytes < 1024) { return bytes + " B"; }
    if (bytes < 1024 * 1024) { return (bytes / 1024).toFixed(1) + " KB"; }
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  document.querySelectorAll("input[type=file][data-preview-target]").forEach(function (input) {
    var target = document.getElementById(input.getAttribute("data-preview-target"));
    if (!target) { return; }
    var currentUrl = null;

    input.addEventListener("change", function () {
      if (currentUrl) { URL.revokeObjectURL(currentUrl); currentUrl = null; }
      target.textContent = "";
      var file = input.files && input.files[0];
      if (!file) { return; }

      currentUrl = URL.createObjectURL(file);
      var el = null;
      if (file.type.indexOf("image/") === 0) {
        el = document.createElement("img");
        el.alt = "Preview of " + file.name;
      } else if (file.type.indexOf("video/") === 0) {
        el = document.createElement("video");
        el.controls = true;
        el.preload = "metadata";
      } else if (file.type.indexOf("audio/") === 0) {
        el = document.createElement("audio");
        el.controls = true;
        el.preload = "metadata";
      }
      if (el) { el.src = currentUrl; target.appendChild(el); }

      var info = document.createElement("p");
      info.className = "small muted";
      info.textContent = file.name + " (" + formatSize(file.size) + ")";
      target.appendChild(info);
    });
  });

  // ---- Favorites without a full page reload ----
  document.querySelectorAll("form[data-favorite-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.fetch) { return; }
      event.preventDefault();
      var button = form.querySelector("button");
      if (button) { button.disabled = true; }

      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (response) {
          if (!response.ok) { throw new Error("Request failed"); }
          return response.json();
        })
        .then(function (data) {
          if (!button) { return; }
          var title = button.getAttribute("aria-label").replace(/^(Add|Remove) /, "").replace(/ (to|from) favorites$/, "");
          button.setAttribute("aria-pressed", data.favorited ? "true" : "false");
          button.setAttribute("aria-label", (data.favorited ? "Remove " : "Add ") + title + (data.favorited ? " from favorites" : " to favorites"));
          button.classList.toggle("is-active", data.favorited);
          var icon = button.querySelector(".fav-icon");
          var label = button.querySelector(".fav-label");
          if (icon) { icon.innerHTML = data.favorited ? "&#9829;" : "&#9825;"; }
          if (label) { label.textContent = data.favorited ? "Saved" : "Save"; }
          button.disabled = false;
        })
        .catch(function () {
          // Fall back to a normal form submission.
          form.submit();
        });
    });
  });

  // ---- Accessible image lightbox (native <dialog>) ----
  var dialog = document.getElementById("lightbox");
  var trigger = document.querySelector(".lightbox-trigger");
  if (dialog && trigger && typeof dialog.showModal === "function") {
    var dialogImage = dialog.querySelector("img");
    trigger.addEventListener("click", function () {
      dialogImage.src = trigger.getAttribute("data-lightbox-src");
      dialogImage.alt = trigger.getAttribute("data-lightbox-alt") || "";
      dialog.showModal();
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog || event.target === dialogImage) { dialog.close(); }
    });
    dialog.addEventListener("close", function () { trigger.focus(); });
  } else if (trigger) {
    // No <dialog> support: open the full-size image in a new tab.
    trigger.addEventListener("click", function () {
      window.open(trigger.getAttribute("data-lightbox-src"), "_blank", "noopener");
    });
  }
})();
