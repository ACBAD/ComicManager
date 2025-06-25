self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);
    // 只处理图片请求
    if (url.toString().includes('/comic/')) {
        let g_res;
        e.respondWith(
            fetch(e.request)
                .then(res => {
                    g_res = res;
                    return res.arrayBuffer();
                })
                .then(buffer => {
                    const arr = new Uint8Array(buffer);
                    for (let i = 0; i < arr.length; i++)
                        arr[i] = arr[i] ^ 0xFF;
                    return new Response(arr, {
                        status: g_res.status
                    });
                })
        );
    }
});