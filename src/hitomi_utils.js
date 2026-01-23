const SUBMIT_BUTTON_DOM = document.getElementById('submitBtn');

SUBMIT_BUTTON_DOM.addEventListener('click', ev => {
    ev.preventDefault();
    const hitomi_id = document.getElementById('hitomi-id-input').value;
    window.location.href = `/hitomi/add?source_document_id=${hitomi_id}`;
})

const LOADING_ICON_DOM = document.getElementById('status-msg');
const SEARCH_BUTTON_DOM = document.getElementById('searchBtn');
let start_loading_timer = () => {};
SEARCH_BUTTON_DOM.addEventListener('click', ev => {
    ev.preventDefault();
    const search_string = document.getElementById('search-string').value;
    ev.target.disabled = true;
    LOADING_ICON_DOM.style.display = '';
    put_results_on_page = () => {};
    do_search();
    results
})

