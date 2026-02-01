const SUBMIT_BUTTON_DOM = document.getElementById('submitBtn');

SUBMIT_BUTTON_DOM.addEventListener('click', ev => {
    ev.preventDefault();
    const hitomi_id = document.getElementById('hitomi-id-input').value;
    window.location.href = `/hitomi/add?source_document_id=${hitomi_id}`;
})

/**
 * @typedef {Object} Language
 * @property {string} name
 * @property {number} galleryid
 * @property {string} language_localname
 * @property {string} url
 */

/**
 * @typedef {Object} Parody
 * @property {string} parody - 保留原始单数形式字段名
 * @property {string} url
 */

/**
 * @typedef {Object} Group
 * @property {string} group
 * @property {string} url
 */

/**
 * @typedef {Object} Tag
 * @property {string} tag
 * @property {string} url
 * @property {string|number} [male=""] - 对应 Python 的 Optional[str]，支持 int 强转输入
 * @property {string|number} [female=""] - 对应 Python 的 Optional[str]，支持 int 强转输入
 */

/**
 * @typedef {Object} PageInfo
 * @property {number} hasavif
 * @property {string} hash
 * @property {number} height
 * @property {number} width
 * @property {string} name
 */

/**
 * @typedef {Object} Character
 * @property {string} character
 * @property {string} url
 */

/**
 * @typedef {Object} Artist
 * @property {string} artist
 * @property {string} url
 */

/**
 * @typedef {Object} Comic
 * @property {string|number} id - 原始输入可能为 int，内部逻辑视作 string 处理
 * @property {string} title
 * @property {string} type
 * @property {string} language
 * @property {string} language_localname
 * @property {string} date
 * @property {string} galleryurl
 * @property {number} blocked
 * @property {PageInfo[]} files
 * @property {Language[]} languages
 * @property {Parody[]} [parodys=[]]
 * @property {Tag[]} [tags=[]]
 * @property {Character[]} [characters=[]]
 * @property {Artist[]} [artists=[]]
 * @property {string|null} [datepublished=null]
 * @property {number[]|null} [related=null]
 * @property {Group[]|null} [groups=null]
 * @property {string|null} [videofilename=null]
 * @property {string|null} [japanese_title=null]
 * @property {string|null} [video=null]
 * @property {*[]} scene_indexes - 对应 list[Any]
 */

const LOADING_ICON_DOM = document.getElementById('status-msg');
const SEARCH_BUTTON_DOM = document.getElementById('searchBtn');
const COMIC_LIST_DIV = document.getElementById('comic-list');
SEARCH_BUTTON_DOM.addEventListener('click', ev => {
    ev.preventDefault();
    const search_string = document.getElementById('search-string').value;
    ev.target.disabled = true;
    LOADING_ICON_DOM.style.display = '';
    fetch(`/api/documents/hitomi/search?search_str=${search_string}`).then(response => {
        if(!response.ok)
            throw Error('请求返回错误码: ' + response.status);
        return response.json();
    }).then(json_result => {
        // noinspection UnnecessaryLocalVariableJS
        /** @type {Array<Comic>}**/
        let comic_infos = json_result;
        LOADING_ICON_DOM.style.display = 'none';
        COMIC_LIST_DIV.style.display = '';
        comic_infos.forEach(comic_info => {
            let comic_line_a = document.createElement('a');
            comic_line_a.href = `/hitomi/add?source_document_id=${comic_info.id}`;
            comic_line_a.target = '_blank';
            comic_line_a.text = comic_info.title;
            let comic_line_h3 = document.createElement('h3');
            comic_line_h3.appendChild(comic_line_a);
            COMIC_LIST_DIV.appendChild(comic_line_h3);
        })
    }).catch(reason => {
        console.error(reason);
        alert(reason);
        LOADING_ICON_DOM.style.display = 'none';
    });
})

