const API_GET_TAGS = '/api/tags/hitomi/missing_tags';
const API_SUBMIT = '/api/documents/hitomi/add';
const API_GET_TAG_GROUPS = '/api/tags'

let globalSourceDocId = null;

/**
 * @type {{[tag_name: string]: number}}
 */
let tag_dict = {};

const statusMsg = document.getElementById('status-msg');
const submitBtn = document.getElementById('submitBtn');

/**
 * @param {string} err
 */
function setErrorMessage(err){
    console.error(err);
    submitBtn.disabled = "disabled";
    statusMsg.style.display = 'block';
    statusMsg.innerHTML = `<span style="color:red">错误: ${err}</span>`;
}

/**
 * @typedef {Array<{name: string, group_id: ?number}>} MissingTags
 */

/**
 * @return Promise<MissingTags>
 * @param {number} source_comic_id
 */
async function getMissingTags(source_comic_id){
    const response = await fetch(`${API_GET_TAGS}?source_document_id=${source_comic_id}`);
    if (!response.ok)throw new Error(`获取tag失败, 错误码: ${response.status} 详情 ${await response.text()}`);
    return await response.json();
}

document.addEventListener('DOMContentLoaded', async () => {
    const formContent = document.getElementById('dynamic-fields');
    let tag_group_resp = await fetch(API_GET_TAG_GROUPS);
    if(!tag_group_resp.ok) {
        setErrorMessage(`请求tag组失败, 错误码: ${tag_group_resp.status}`)
    }
    tag_dict = await tag_group_resp.json();
    const params = new URLSearchParams(window.location.search);
    const rawSourceDocId = params.get('source_document_id');
    if (!rawSourceDocId){
        setErrorMessage("缺少必需参数: source_document_id");
        return;
    }
    globalSourceDocId = rawSourceDocId;
    let tags;
    try{
        tags = await getMissingTags(parseInt(rawSourceDocId));
    }catch (err){
        setErrorMessage(err.message);
        return;
    }
    // === 修改点开始：处理空数组逻辑 ===
    if (tags.length === 0) {
        // 状态 A: 完备状态 (不阻断，显示提示，显示按钮)
        statusMsg.innerHTML = `
            <div class="success-icon">✓</div>
            <strong>当前文档标签已完备</strong><br>
            <span style="font-size: 0.9em; color: #888">无需补录信息，请直接点击提交</span>
        `;
        statusMsg.style.display = 'block'; // 确保显示
        submitBtn.disabled = false;
        return;
    }
    // 状态 B: 需要录入 (隐藏提示，生成表单)
    statusMsg.style.display = 'none';

    tags.forEach(tag => {
        const section = document.createElement('div');
        section.className = 'tag-section';
        section.dataset.tagName = tag.name;

        const title = document.createElement('span');
        title.className = 'tag-name';
        title.textContent = tag.name;
        section.appendChild(title);

        if (tag.group_id === null) {
            const groupRow = document.createElement('div');
            groupRow.className = 'form-group';
            groupRow.innerHTML = `
                <label>组 ID (Group ID)</label>
                <input type="number" class="form-control input-group-id" placeholder="请输入组 ID">
            `;
            section.appendChild(groupRow);
        }else {
            let tag_name = title.textContent;
            title.textContent = `${tag_dict[tag.group_id]}: ${tag_name}`
        }

        const dbRow = document.createElement('div');
        dbRow.className = 'form-group';
        dbRow.innerHTML = `
            <label>数据库名称 (Database Name)</label>
            <input type="text" class="form-control input-db-name" required placeholder="请输入数据库名称">
        `;
        section.appendChild(dbRow);
        formContent.appendChild(section);
    });
    submitBtn.disabled = false;

});

// 3. 提交逻辑
document.getElementById('entryForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    if (globalSourceDocId === null) {
        setErrorMessage("提交失败：缺少必要的 Source ID 信息");
        return;
    }

    submitBtn.disabled = true;
    submitBtn.innerText = '正在提交...';

    const tagsMap = {};
    const sections = document.querySelectorAll('.tag-section');

    // 如果 sections 为空（即 tags 为空），循环不会执行，tagsMap 为 {}
    // 这符合 "inexistent_tags: {}" 的预期
    sections.forEach(section => {
        const tagName = section.dataset.tagName;
        const dbInput = section.querySelector('.input-db-name');
        const groupInput = section.querySelector('.input-group-id');
        const dbName = dbInput ? dbInput.value.trim() : "";
        let groupId = null;
        if (groupInput && groupInput.value.trim() !== "") {
            groupId = parseInt(groupInput.value.trim(), 10);
            if (isNaN(groupId)) groupId = null;
        }
        tagsMap[tagName] = [groupId, dbName];
    });

    const payload = {
        source_id: 1,
        source_document_id: globalSourceDocId,
        inexistent_tags: tagsMap // 可能是空对象，符合 Pydantic 模型
    };

    const postRes = await fetch(API_SUBMIT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    const result = await postRes.json();

    if (postRes.ok && result.success) {
        window.location.href = result.redirect_url;
    } else {
        if (result.message)
            setErrorMessage(result.message);
        else if (postRes.status === 403){
            setErrorMessage('你无权添加本子')
        }
        else
            setErrorMessage('添加失败, 服务器未返回原因')
    }
});