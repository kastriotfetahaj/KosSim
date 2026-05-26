$(function () {
    if (location.hash) {
        var e = $(location.hash);
        if (e.length) {
            e.collapse('show');
            console.log(e.parent());
            e.parent()[0].scrollIntoView();
        }
    }
});