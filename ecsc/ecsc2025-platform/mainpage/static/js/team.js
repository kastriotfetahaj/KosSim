let changeProfile = function () {
    let xhr = new XMLHttpRequest();
    xhr.open("POST", location.origin + "/team/edit/info", true);
    xhr.setRequestHeader("Content-type", "application/x-www-form-urlencoded");
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            window.location.reload();
        }
    };
    let csrf = document.getElementsByName("csrfmiddlewaretoken")[0];
    let params = "csrfmiddlewaretoken=" + csrf.value;
    params += "&new_irc=" + encodeURIComponent(document.getElementById("irc").value);
    params += "&new_web_site=" + encodeURIComponent(document.getElementById("website").value);
    params += "&new_affiliation=" + encodeURIComponent(document.getElementById("affiliation").value);
    xhr.send(params);
};

document.getElementById("team_logo").onmouseover = function () {
    document.getElementById("logo_edit").hidden = false;
};

document.getElementById("team_logo").onmouseout = function () {
    document.getElementById("logo_edit").hidden = true;
};

document.getElementById("logo_edit").onclick = function () {
    document.getElementById("file-input").click();
};

if (document.getElementById("file-input")) {
    document.getElementById("file-input").onchange = function () {
        document.getElementById("file-input").parentElement.submit();
    };
}

const teamInputs = document.getElementsByClassName("settings");
for (let input of Array.from(teamInputs)) {
    if (input.tagName == "INPUT" && !input.readOnly) {
        input.addEventListener("change", changeProfile);
    }
}

$(function () {
    $('[data-toggle="tooltip"]').tooltip();
    $('[data-toggle="popover"]').popover();
});

for (let form of document.querySelectorAll("form.require-confirmation")) {
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (confirm(e.target.dataset.confirmation || "Are you sure?")) {
            e.target.submit();
        }
    });
}
