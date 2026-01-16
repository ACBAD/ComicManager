document.addEventListener('DOMContentLoaded', () => {
    const dropdown_seletor = document.getElementById("category-select");
    const dropdown_input = document.getElementById('dropdown-input');
    $.ajax({
        type: 'GET',
        url: '/api/tags',
        success: function (response) {
            for (const [group_id, group_name] of Object.entries(response)) {
                let new_option = document.createElement('option');
                new_option.value = group_id;
                new_option.textContent = group_name.toString();
                dropdown_seletor.appendChild(new_option);
            }
            dropdown_input.placeholder = 'Tag组更新完成, 等待选择tag组';
        },
        error: function () {
            dropdown_input.placeholder = 'Tag组更新失败, 禁用一切';
            throw new Error();
        }
    })
    const dropdown_list = document.getElementById('dropdown-list');
    // 添加事件监听，使得点击列表项后填充输入框
    dropdown_list.addEventListener('click', (e) => {
        if (e.target.tagName === 'LI') {
            document.getElementById('dropdown-input').value = e.target.textContent;
            dropdown_list.style.display = 'none';  // 选中后隐藏下拉列表
        }
    });
    // 点击输入框以外区域时隐藏下拉列表
    document.addEventListener('click', (e) => {
        if (!dropdown_list.contains(e.target) && !document.getElementById('dropdown-input').contains(e.target))
            dropdown_list.style.display = 'none';
    });
});

// 根据不可输入下拉列表中的选择来更新可输入下拉列表内容
function updateDropdownList() {
    const group_selector = document.getElementById('category-select');
    const dropdown_list = document.getElementById('dropdown-list');
    const dropdown_input = document.getElementById('dropdown-input');
    dropdown_input.placeholder = '等待更新';
    dropdown_list.innerHTML = '';
    $.ajax({
        type: 'GET',
        url: '/api/tags?group_id=' + group_selector.value,
        success: function (response) {
            for (const [tag_name, tag_id] of Object.entries(response)) {
                let new_option = document.createElement('li');
                new_option.setAttribute('tag-id', tag_id.toString());
                new_option.textContent = tag_name;
                dropdown_list.appendChild(new_option);
            }
            dropdown_input.placeholder = '更新完成, 输入tag部分以选择';
        },
        error: function () {
            dropdown_input.placeholder = '更新失败';
        }
    })
    // 更新输入框内容
    filterList(); // 输入框内容不变时也要调用一次以保证正确的显示
}

// 根据输入框内容实时过滤下拉列表
function filterList() {
    const input = document.getElementById('dropdown-input');
    const filter = input.value.toLowerCase();
    const dropdown_list = document.getElementById('dropdown-list');
    // 显示下拉列表
    dropdown_list.style.display = 'block';
    for (let list_index = 0; list_index < dropdown_list.children.length; list_index++) {
        let now_list_option = dropdown_list.children[list_index];
        const text = now_list_option.textContent;
        // 同时根据分类选择和输入内容进行过滤
        if (text.toLowerCase().indexOf(filter) > -1)
            now_list_option.style.display = '';
        else
            now_list_option.style.display = 'none';
    }
    // 如果输入为空且没有选中项，隐藏下拉列表
    if (filter === '')
        dropdown_list.style.display = 'none';
}

function submitAuthorSearch(event) {
    const author_name = event.target.textContent;
    let author_input = document.getElementById('document-input');
    author_input.value = author_name;
    document.getElementById('dropdown-input').value = '';
    searchDocuments(1);
}

let documentsContainer;
$().ready(function () {
    documentsContainer = document.getElementById('list-container');
    const title_items = document.getElementsByClassName('title-item');
    for (let i = 0; i < title_items.length; i++) {
        title_items[i].addEventListener('click', switchPage);
    }
    const now_page_item = document.getElementById('now-page');
    const total_page_item = document.getElementById('total-page');
    const now_page_bottom_item = document.getElementById('now-page-bottom');
    const total_page_bottom_item = document.getElementById('total-page-bottom');
    const page_sync_observer = new MutationObserver(function (mutations) {
        // noinspection JSUnusedLocalSymbols
        mutations.forEach(mutation => {
            now_page_bottom_item.textContent = now_page_item.textContent;
            total_page_bottom_item.textContent = total_page_item.textContent;
        });
    });
    page_sync_observer.observe(now_page_item, {characterData: true, subtree: true, childList: true});
    page_sync_observer.observe(total_page_item, {characterData: true, subtree: true, childList: true});
})

function switchPage(event) {
    if (event.target.id === 'page-step') {
        return;
    }
    const nowPage = parseInt(document.getElementById('now-page').textContent, 10);
    const totalPage = parseInt(document.getElementById('total-page').textContent, 10);
    const pageStep = parseInt(document.getElementById('page-step').value, 10) ?
        parseInt(document.getElementById('page-step').value, 10) : 1;
    let targetPage = 1;
    if (event.target.id.startsWith('prev-page-button')) {
        if (nowPage <= pageStep) return;
        targetPage = nowPage - pageStep;
    } else if (event.target.id.startsWith('next-page-button')) {
        if (nowPage + pageStep > totalPage) return;
        targetPage = nowPage + pageStep;
    } else {
        alert('不是翻页按钮，无法应用功能');
    }
    searchDocuments(targetPage);
}


/**
 * @typedef {{target_tag: number, author_name: string, page: number}} SearchArgs
 */

/**
 *
 * @param {number} target_page
 * @return SearchArgs
 */

function updateSearchArgs(target_page) {
    if (target_page === null)target_page = 1;
    let search_args = {target_tag: 0, author_name: '', page: target_page};
    const tag_name = document.getElementById('dropdown-input').value;
    const tag_select_list = document.getElementById('dropdown-list');
    let tag_id = 0;
    for (let i = 0; i < tag_select_list.children.length; i++) {
        let tag_select = tag_select_list.children[i];
        if (tag_select.textContent === tag_name) {
            tag_id = tag_select.getAttribute('tag-id');
            console.log('已查询到指定tag: ' + tag_id)
        }
    }
    search_args.author_name = document.getElementById('document-input').value;
    search_args.target_tag = tag_id;
    return search_args;
}


/**
 * 请求删除文档
 * @param {number} document_id
 */
function requestDeleteDocument(document_id) {
    const is_confirmed = confirm(`确定要删除id为${document_id}的文档吗`)
    if (!is_confirmed) return;
    $.ajax({
        type: 'DELETE',
        // 将参数拼接到 URL query string 中，确保 FastAPI 能正确读取
        url: '/api/documents/' + document_id,
        success: function (response) {
            alert('删除成功');
            // 3. 刷新当前页面列表
            const now_page = parseInt(document.getElementById('now-page').textContent, 10);
            searchDocuments(now_page);
        },
        error: function (xhr) {
            // 处理错误返回 (403 Forbidden 或 400 Bad Request)
            let errorMsg = "删除失败";
            if (xhr.responseJSON && xhr.responseJSON.detail) {
                errorMsg += ": " + xhr.responseJSON.detail;
            } else if (xhr.status === 403) {
                errorMsg += ": 权限不足";
            } else {
                errorMsg += ": 未知错误";
            }
            alert(errorMsg);
        }
    });
}

/**
 * @typedef {Object} DocumentInfo
 * @property {number} document_id - 对应 document_id (PK)
 * @property {string} title - 对应 title
 * @property {string} file_path - 对应 file_path
 * @property {?string} series_name - 对应 Optional[str]，使用 ? 表示可为 null
 * @property {?number} volume_number - 对应 Optional[int]
 */

/**
 * @typedef {Object} TagInfo
 * @property {number} tag_id - 对应 tag_id (PK)
 * @property {string} name - 对应 name
 * @property {?string} hitomi_alter - 对应 Optional[str]
 * @property {?number} group_id - 对应 Optional[int]
 */

/**
 * @typedef {Object} AuthorInfo
 * @property {number} author_id
 * @property {string} name - 对应 name
 */

/**
 * @typedef {Object} DocumentMeta
 * @property {DocumentInfo} document_info
 * @property {Array<TagInfo>} document_tags
 * @property {Array<AuthorInfo>} document_authors
 * @property {Array<string>} document_pages
 */


/**
 * 构造文档
 * @param {DocumentMeta} document_meta
 * @returns {HTMLDivElement}
 */
function constructDocument(document_meta) {
    let document_id = document_meta.document_info.document_id;
    console.log(`现在开始构造文档: ${document_id}`);
    let document_item = document.createElement('div');
    document_item.className = 'list-item';
    let document_thumbnail = document.createElement('img');
    document_thumbnail.className = 'thumbnail';
    document_thumbnail.src = `/api/documents/${document_meta.document_info.document_id}/thumbnail`;
    document_item.appendChild(document_thumbnail);
    let document_details = document.createElement('div');
    document_details.className = 'details'
    let document_title = document.createElement('h3');
    let document_link = document.createElement('a');
    document_link.href = `/show_document/${document_id}`;
    document_link.textContent = document_meta.document_info.title;
    document_title.appendChild(document_link);
    document_details.appendChild(document_title);
    document_meta.document_authors.forEach(author_name => {
        let document_author = document.createElement('button');
        document_author.addEventListener("click", submitAuthorSearch);
        document_author.textContent = author_name.name;
        document_details.appendChild(document_author);
    })
    let document_tags = document.createElement('div');
    document_tags.className = 'tag-info';
    document_meta.document_tags.forEach(tag => {
        let single_tag = document.createElement('span');
        single_tag.textContent = tag.name;
        document_tags.appendChild(single_tag);
    })
    document_details.appendChild(document_tags);
    let delete_btn = document.createElement('button');
    delete_btn.textContent = '删除';
    delete_btn.style.color = 'red'; // 简单样式，也可在css中定义class
    delete_btn.style.marginLeft = '10px';
    delete_btn.style.cursor = 'pointer';
    // 绑定点击事件，调用删除逻辑
    delete_btn.onclick = function() {
        requestDeleteDocument(document_id);
    };
    document_details.appendChild(delete_btn);

    document_item.appendChild(document_details);
    return document_item;
}


/**
 * 定义 HTMX 事件的 detail 结构
 * @typedef {Object} HtmxRequestDetail
 * @property {HTMLElement} elt - 触发请求的元素 (The triggering element)
 * @property {HTMLElement} target - 目标交换元素 (The target of the content swap)
 * @property {XMLHttpRequest} xhr - 原生的 XHR 对象 (The XMLHttpRequest)
 * @property {Object} requestConfig - 请求配置 (Request configuration)
 * @property {string} path - 请求的路径
 * @property {boolean} successful - 请求是否成功 (2xx)
 * @property {boolean} failed - 请求是否失败
 */

/**
 * 定义 HTMX 事件本身
 * 这是一个 CustomEvent，但它的 detail 属性是我们上面定义的结构
 * @typedef {CustomEvent & { detail: HtmxRequestDetail }} HtmxAfterRequestEvent
 */

// noinspection JSUnusedGlobalSymbols
/**
 * @param {HtmxAfterRequestEvent} evt
 */
function documentCallback(evt){
        // 1. 获取上下文
    const targetDiv = evt.detail.elt;
    const xhr = evt.detail.xhr;
    console.log(`触发documentCallback`)
    // 2. 检查请求是否成功
    if (evt.detail.successful) {
        try {
            // 3. 成功：调用构建函数
            const responseData = JSON.parse(xhr.response);
            const newElement = constructDocument(responseData);

            // 4. 替换原对象 (原 div 会从 DOM 中移除，被新 div 取代)
            if (targetDiv && targetDiv.parentNode) {
                targetDiv.replaceWith(newElement);
            }
        } catch (err) {
            console.error("构建 DOM 时出错:", err);
            targetDiv.innerHTML = `<span style="color:red">数据处理异常</span>`;
        }
    } else {
        // 5. 失败：在原 div 中显示报错信息
        const errorMsg = xhr.statusText || "未知网络错误";
        const errorCode = xhr.status;

        targetDiv.innerHTML = `
            <div style="color: red; border: 1px solid red; padding: 10px;">
                <strong>加载失败</strong>
                <p>错误代码: ${errorCode}</p>
                <p>错误信息: ${errorMsg}</p>
            </div>
        `;
    }
}


/**
 * @param {{total_count: number, results: Array<number>}} response
 */
function unpackSearchResponse(response){
    documentsContainer.innerHTML = '';
    let document_count = response.total_count;
    const total_page_item = document.getElementById('total-page');
    total_page_item.textContent = Math.ceil(document_count / 10).toString();
    console.log('开始构造文档列表')
    response.results.forEach(document_id => {
        let document_item = document.createElement('div');
        document_item.setAttribute('hx-get', `/api/documents/${document_id}`);
        document_item.setAttribute('hx-trigger', 'load')
        document_item.setAttribute('hx-on::after-request', 'documentCallback(event)')
        // document_item.setAttribute('hx-swap', 'none');
        documentsContainer.appendChild(document_item);
    });
    htmx.process(documentsContainer);
}


/**
 *
 * @param {number} target_page
 */
function searchDocuments(target_page) {
    let search_args = updateSearchArgs(target_page);
    console.log('查询参数: ' + search_args)
    let query_url_params = new URLSearchParams(Object.entries(search_args).map(([key, value]) => [key, String(value)])).toString();
    $.ajax({
        type: 'GET',
        url: `/api/documents/?${query_url_params}`,
        contentType: 'application/json;charset=UTF-8',
        success: function (response) {
            console.log('search_document 成功返回');
            unpackSearchResponse(response);
        }
    })
    const now_page_item = document.getElementById('now-page');
    now_page_item.textContent = search_args.target_page.toString();
}

