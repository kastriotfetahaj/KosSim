let start_date = document.querySelector("#countdown").getAttribute("data-date");
let start = new Date(start_date).getTime();

function timer() {
    var msec = start - new Date().getTime();
    if (msec < 0) msec = 0;
    if (msec == 0) {
        document.querySelector("#countdown-final").style.display = "unset";
    }
    var sec = Math.floor(msec / 1000);
    var mm = Math.floor(sec / 60);
    var hh = Math.floor(mm / 60);
    var dd = Math.floor(hh / 24);
    window.days.innerText = dd;
    window.hours.innerText = hh % 24;
    window.mins.innerText = mm % 60;
    window.sec.innerText = sec % 60;
}

window.onload = function () {
    timer();
    setInterval(function () {
        timer();
    }, 1000);
}
