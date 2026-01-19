const SUBMIT_BUTTON_DOM = document.getElementById('submitBtn');

SUBMIT_BUTTON_DOM.addEventListener('click', ev => {
    ev.preventDefault();
    const hitomi_id = document.getElementById('hitomi-id-input').value;
    window.location.href = `/hitomi/add?source_document_id=${hitomi_id}`;
})

const LOADING_ICON_DOM = document.getElementById('status-msg');
const SEARCH_BUTTON_DOM = document.getElementById('searchBtn');

SEARCH_BUTTON_DOM.addEventListener('click', ev => {
    ev.preventDefault();
    const search_string = document.getElementById('search-string').value;
    LOADING_ICON_DOM.style.display = '';

})

