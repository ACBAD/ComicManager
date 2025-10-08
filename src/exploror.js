document.addEventListener('DOMContentLoaded', () => {
    const dropdownList = document.getElementById('dropdown-list');
    // 添加事件监听，使得点击列表项后填充输入框
    dropdownList.addEventListener('click', (e) => {
        if (e.target.tagName === 'LI') {
            document.getElementById('dropdown-input').value = e.target.textContent;
            dropdownList.style.display = 'none';  // 选中后隐藏下拉列表
        }
    });
    // 点击输入框以外区域时隐藏下拉列表
    document.addEventListener('click', (e) => {
        if (!dropdownList.contains(e.target) && !document.getElementById('dropdown-input').contains(e.target))
            dropdownList.style.display = 'none';
    });
    updateDropdownList();
});
// 根据不可输入下拉列表中的选择来更新可输入下拉列表内容
function updateDropdownList() {
    const groupSelector = document.getElementById('category-select');
    const dropdownList = document.getElementById('dropdown-list');
    const dropdownInput = document.getElementById('dropdown-input');
    dropdownList.innerHTML = '';
    $.ajax({
        type: 'GET',
        url: '/get_tags/' + groupSelector.value,
        success: function (response){
            dropdownInput.placeholder = '更新完成, 输入tag部分以选择';
            for (const [tag_name, tag_id] of Object.entries(response)){
                let newOption = document.createElement('li');
                newOption.setAttribute('tag-id', tag_id.toString());
                newOption.textContent = tag_name;
                dropdownList.appendChild(newOption);
            }
        },
        error: function (){
            dropdownInput.placeholder = '更新失败';
        }
    })
    // 更新输入框内容
    filterList(); // 输入框内容不变时也要调用一次以保证正确的显示
}

// 根据输入框内容实时过滤下拉列表
function filterList() {
    const input = document.getElementById('dropdown-input');
    const filter = input.value.toLowerCase();
    const dropdownList = document.getElementById('dropdown-list');
    // 显示下拉列表
    dropdownList.style.display = 'block';
    for(let list_index=0; list_index<dropdownList.children.length;list_index++) {
        let nowListOption = dropdownList.children[list_index];
        const text = nowListOption.textContent;
        // 同时根据分类选择和输入内容进行过滤
        if (text.toLowerCase().indexOf(filter) > -1)
            nowListOption.style.display = '';
         else
            nowListOption.style.display = 'none';
    }
    // 如果输入为空且没有选中项，隐藏下拉列表
    if (filter === '')
        dropdownList.style.display = 'none';
}

function submitAuthorSearch(event) {
    const author_name = event.target.textContent;
    let author_input = document.getElementById('comic-input');
    author_input.value = author_name;
    document.getElementById('dropdown-input').value = '';
    submitSearchArgs();
}

let comicsContainer;
$().ready(function () {
    comicsContainer = document.getElementById('list-container');
    const title_items = document.getElementsByClassName('title-item');
    for (let i = 0; i < title_items.length; i++) {
        title_items[i].addEventListener('click', switchPage);
    }
    const now_page_item = document.getElementById('now-page');
    const total_page_item = document.getElementById('total-page');
    const now_page_bottom_item = document.getElementById('now-page-bottom');
    const total_page_bottom_item = document.getElementById('total-page-bottom');
    const page_sync_observer = new MutationObserver(function(mutations) {
        mutations.forEach(mutation => {
            now_page_bottom_item.textContent = now_page_item.textContent;
            total_page_bottom_item.textContent = total_page_item.textContent;
        });
    });
    page_sync_observer.observe(now_page_item, {characterData: true, subtree:true, childList:true});
    page_sync_observer.observe(total_page_item, {characterData: true, subtree:true, childList:true});
});
let searchArgs = {comic_tag: 0, author: '', target_page: null};

function switchPage(event){
    if(event.target.id === 'page-step'){return;}
    const nowPage = parseInt(document.getElementById('now-page').textContent, 10);
    const totalPage = parseInt(document.getElementById('total-page').textContent, 10);
    const pageStep = parseInt(document.getElementById('page-step').value, 10) ?
        parseInt(document.getElementById('page-step').value, 10) : 1;
    if (event.target.id.startsWith('prev-page-button')){
        if(nowPage <= pageStep)return;
        searchArgs.target_page = nowPage - pageStep;
    }
    else if (event.target.id.startsWith('next-page-button')){
        if(nowPage + pageStep > totalPage) return;
        searchArgs.target_page = nowPage + pageStep;
    }
    else{
        alert('不是翻页按钮，无法应用功能');
    }
    requestComics();
}

function updateSearchArgs(){
    const tagName = document.getElementById('dropdown-input').value;
    const tagSelectList = document.getElementById('dropdown-list');
    let tagID = 0;
    for (let i=0;i<tagSelectList.children.length;i++){
        let tagSelect = tagSelectList.children[i];
        if(tagSelect.textContent === tagName)tagID = tagSelect.getAttribute('tag-id');
    }
    searchArgs.author = document.getElementById('comic-input').value;
    searchArgs.comic_tag = tagID;
}

function createComic(item){
    console.log(item);
    let comic_item = document.createElement('div');
    comic_item.className = 'list-item';
    let comic_thumbnail = document.createElement('img');
    comic_thumbnail.className = 'thumbnail';
    comic_thumbnail.src = '/comic_pic/' + item[0] + '/-1';
    comic_item.appendChild(comic_thumbnail);
    let comic_details = document.createElement('div');
    comic_details.className = 'details'
    let comic_title = document.createElement('h3');
    let comic_link = document.createElement('a');
    comic_link.href = '/show_comic/' + item[0];
    comic_link.textContent = item[1];
    comic_title.appendChild(comic_link);
    comic_details.appendChild(comic_title);
    let comic_author = document.createElement('button');
    comic_author.addEventListener("click", submitAuthorSearch);
    comic_author.textContent = item[5];
    comic_details.appendChild(comic_author);
    let comic_tags = document.createElement('div');
    comic_tags.className = 'tag-info';
    item[6].forEach(tag =>{
        let single_tag = document.createElement('span');
        single_tag.textContent = tag;
        comic_tags.appendChild(single_tag);
    })
    comic_details.appendChild(comic_tags);
    comic_item.appendChild(comic_details);
    comicsContainer.appendChild(comic_item);
}

function requestComics(){
    $.ajax({
        type: 'POST',
        url: '/search_comic',
        data: JSON.stringify(searchArgs),
        contentType: 'application/json;charset=UTF-8',
        success: function (response){
            console.log('search_comic 成功返回');
            comicsContainer.innerHTML = '';
            let comic_count = response.total_count;
            let comics_info = response.comics_info;
            const total_page_item = document.getElementById('total-page');
            total_page_item.textContent = Math.ceil(comic_count/10).toString();
            comics_info.forEach(createComic);
        }
    })
    const now_page_item = document.getElementById('now-page');
    now_page_item.textContent = searchArgs.target_page.toString();
}

function submitSearchArgs(){
    searchArgs.target_page = 1;
    updateSearchArgs();
    requestComics();
}
