for (let form of document.querySelectorAll("form.require-confirmation")) {
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (confirm(e.target.dataset.confirmation || "Are you sure?")) {
            e.target.submit();
        }
    });
}
