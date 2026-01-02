document.addEventListener('DOMContentLoaded', () => {
    const dropdown_seletor = document.getElementById("category-select");
    const dropdown_input = document.getElementById('dropdown-input');
    $.ajax({
        type: 'GET',
        url: '/get_tag_groups',
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
        url: '/get_tags/' + group_selector.value,
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
    requestDocuments(1);
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
    requestDocuments(targetPage);
}


/**
 * @typedef {{target_tag: number, author_name: string, target_page: number}} SearchArgs
 */

/**
 *
 * @param {number} target_page
 * @return SearchArgs
 */

function updateSearchArgs(target_page) {
    if (target_page === null)target_page = 1;
    let searchArgs = {target_tag: 0, author_name: '', target_page: target_page};
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
    searchArgs.author_name = document.getElementById('document-input').value;
    searchArgs.target_tag = tag_id;
    return searchArgs;
}

/**
 * 将标签绑定到指定的文档上
 * @param {DocumentInfo} document_info - 传入的文档信息对象
 * @param {Array<TagInfo>} tags_info - 传入的标签信息对象
 * @param {Array<string>} author_list - 传入的作者信息对象
 * @returns {void}
 */
function createDocument(document_info, tags_info, author_list) {
    console.log(document_info, tags_info, author_list);
    let document_item = document.createElement('div');
    document_item.className = 'list-item';
    let document_thumbnail = document.createElement('img');
    document_thumbnail.className = 'thumbnail';
    document_thumbnail.src = '/document_content/' + document_info.document_id + '/-1';
    document_item.appendChild(document_thumbnail);
    let document_details = document.createElement('div');
    document_details.className = 'details'
    let document_title = document.createElement('h3');
    let document_link = document.createElement('a');
    document_link.href = '/get_document/' + document_info.document_id;
    document_link.textContent = document_info.title;
    document_title.appendChild(document_link);
    document_details.appendChild(document_title);
    author_list.forEach(author_name => {
        let document_author = document.createElement('button');
        document_author.addEventListener("click", submitAuthorSearch);
        document_author.textContent = author_name;
        document_details.appendChild(document_author);
    })
    let document_tags = document.createElement('div');
    document_tags.className = 'tag-info';
    tags_info.forEach(tag => {
        let single_tag = document.createElement('span');
        single_tag.textContent = tag.name;
        document_tags.appendChild(single_tag);
    })
    document_details.appendChild(document_tags);
    document_item.appendChild(document_details);
    documentsContainer.appendChild(document_item);
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
 * @typedef {Object} SearchDocumentResponse
 * @property {number} total_count
 * @property {{[doc_id: number]: Array<string>}} document_authors
 * @property {{[doc_id: number]: DocumentInfo}} documents_info - 对应 dict[int, Document]
 * @property {{[doc_id: number]: Array<TagInfo>}} tags - 对应 dict[int, list[Tag]]，注意这里是数组
 */

/**
 *
 * @param {number} target_page
 */
function requestDocuments(target_page) {
    let search_args = updateSearchArgs(target_page);
    let search_args_json = JSON.stringify(search_args);
    console.log('查询参数: ' + search_args_json)
    $.ajax({
        type: 'POST',
        url: '/search_document',
        data: search_args_json,
        contentType: 'application/json;charset=UTF-8',
        success: function (response) {
            console.log('search_document 成功返回');
            documentsContainer.innerHTML = '';
            let document_count = response.total_count;
            const total_page_item = document.getElementById('total-page');
            total_page_item.textContent = Math.ceil(document_count / 10).toString();
            console.log('开始构造文档列表')
            let document_map = response.documents_info;
            let tag_map = response.tags;
            let author_map = response.document_authors;
            // 2. 遍历文档字典
            // 使用 Object.keys() 或 for...in 均可，这里推荐 Object.entries 以同时获取 ID 和 对象
            Object.entries(document_map)
                .sort((a, b) => parseInt(b[0]) - parseInt(a[0]))
                .forEach(([key, doc_info]) => {
                // 注意：Object 的键在 JS 运行时是字符串，如果需要数字类型可能需要 parseInt(key)
                // 但作为索引访问对象属性时，字符串 key 是安全的
                // 3. 通过 ID 在 tags 字典中查找对应的标签数组
                // 添加 || [] 是防御性编程，防止某个文档没有对应的标签记录导致报错
                let relevant_tags = tag_map[key] || [];
                let relevent_authors = author_map[key] || [];
                console.log('开始构造文档' + key)
                createDocument(doc_info, relevant_tags, relevent_authors);
            });
        }
    })
    const now_page_item = document.getElementById('now-page');
    now_page_item.textContent = search_args.target_page.toString();
}

