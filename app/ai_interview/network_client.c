/*
 * AI模拟面试官 — 网络通信模块
 * 负责：A同学
 *
 * 端侧 -> 云端：POST /api/interview，body 为 JSON，音频以 base64 内嵌
 * 云端 -> 端侧：JSON，tts_audio 为 base64 编码的 WAV
 *
 * 依赖（R528 板级配置已具备，无需改 defconfig）：
 *   CONFIG_LIB_CURL            HTTP 客户端（连带 CRYPTO_MBEDTLS / LIB_ZLIB）
 *   CONFIG_NETUTILS_CJSON      JSON 解析
 *   mbedtls/base64.h           base64 编解码（由 CONFIG_LIB_CURL 间接引入）
 *
 * 注意：libcurl 需要 200KB 量级的栈（参考 CONFIG_EXAMPLES_HTTP_STACKSIZE=204800）。
 * 本应用主任务栈已提到 32768，网络调用务必在工作线程（栈 262144）里执行。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>

#include <curl/curl.h>
#include "netutils/cJSON.h"
#include <mbedtls/base64.h>

#include "network_client.h"
#include "app_config.h"

/* 单次响应上限：24kHz 单声道 WAV 的 base64 约 10 秒 640KB，留足余量 */
#define CLOUD_RESP_MAX  (8u * 1024u * 1024u)

/* 请求路径：只配 base URL，路径写死在这里避免两处配置漂移 */
#define CLOUD_PATH_INTERVIEW  "/api/interview"
#define CLOUD_PATH_HEALTH     "/api/health"

static char g_url_interview[192];
static char g_url_health[192];
static int  g_initialized = 0;

const char *cloud_strerror(int rc)
{
    switch (rc) {
        case CLOUD_OK:              return "成功";
        case CLOUD_ERR_HTTP:        return "HTTP 传输失败或非 2xx（多半是网络不通）";
        case CLOUD_ERR_JSON:        return "响应不是合法 JSON 或结构不符协议";
        case CLOUD_ERR_EMPTY_TTS:   return "tts_audio 为空（云端多半缺 API key）";
        case CLOUD_ERR_BAD_AUDIO:   return "解码后不是可播放的 WAV";
        case CLOUD_ERR_NOMEM:       return "内存不足";
        default:                    return "未知错误";
    }
}

/* ---------- 响应缓冲 ---------- */

struct mem_chunk {
    char  *memory;
    size_t size;
};

static size_t write_memory_cb(void *contents, size_t size, size_t nmemb,
                              void *userp)
{
    size_t realsize = size * nmemb;
    struct mem_chunk *mem = (struct mem_chunk *)userp;
    char *ptr;

    /* 超限返回 0 让 curl 以 CURLE_WRITE_ERROR 中止，而不是把内存吃光 */
    if (mem->size + realsize > CLOUD_RESP_MAX) {
        printf("[Cloud] 响应超过上限 %u 字节，中止\n", (unsigned)CLOUD_RESP_MAX);
        return 0;
    }

    ptr = realloc(mem->memory, mem->size + realsize + 1);
    if (ptr == NULL) {
        printf("[Cloud] 响应缓冲分配失败\n");
        return 0;
    }

    mem->memory = ptr;
    memcpy(&(mem->memory[mem->size]), contents, realsize);
    mem->size += realsize;
    mem->memory[mem->size] = '\0';

    return realsize;
}

/* ---------- 初始化 ---------- */

void cloud_init(void)
{
    const char *base;

    if (g_initialized) {
        return;
    }

    curl_global_init(CURL_GLOBAL_ALL);

    base = app_cloud_base_url();
    snprintf(g_url_interview, sizeof(g_url_interview), "%s%s",
             base, CLOUD_PATH_INTERVIEW);
    snprintf(g_url_health, sizeof(g_url_health), "%s%s",
             base, CLOUD_PATH_HEALTH);

    /* ⚠️ 这里**刻意不打印**云端地址（原来有一行 printf，已挪走）。
     * cloud_init() 跑在**工作线程**里，而启动那几秒主线程正在刷 K1/K2/K3 的帮助
     * 信息 —— NuttX 的 stdio 非线程安全，两边的输出会互相踩掉。实测这行地址打印
     * 被吞过两次，而它恰恰是排查"到底用了哪个地址"时唯一的信息来源（台账 §11.28：
     * 那次悬案最后只能改用阴性对照法才问出来）。
     * 现在由主线程在启动工作线程**之前**打印，见 main.c 的 cloud_url_source()。 */

    g_initialized = 1;
}

/* ---------- 账号 token（2026-10-27） ---------- */

static char g_user_token[128];

/* 目标问答轮数（2026-11-01）：随每次面试请求上报；云端建会话时钉住。
 * 默认 10；范围与云端一致（4~30）。 */
static int g_target_rounds = 10;

void cloud_set_target_rounds(int rounds)
{
    if (rounds >= 4 && rounds <= 30) {
        g_target_rounds = rounds;
    }
}

int cloud_target_rounds(void)
{
    return g_target_rounds;
}

void cloud_set_user_token(const char *token)
{
    strncpy(g_user_token, (token != NULL) ? token : "",
            sizeof(g_user_token) - 1);
    g_user_token[sizeof(g_user_token) - 1] = '\0';
}

const char *cloud_user_token(void)
{
    return g_user_token;
}

/* ---------- 申请绑定 token ---------- */

int cloud_bind_start(char *url_out, size_t url_cap,
                     char *token_out, size_t token_cap)
{
    CURL *curl;
    CURLcode rc;
    struct mem_chunk chunk = { NULL, 0 };
    struct curl_slist *headers = NULL;
    cJSON *root = NULL;
    cJSON *item;
    char url[256];
    long status = 0;
    int ret = CLOUD_ERR_JSON;

    if (url_out == NULL || token_out == NULL || url_cap == 0 || token_cap == 0) {
        return CLOUD_ERR_NOMEM;
    }
    url_out[0] = '\0';
    token_out[0] = '\0';

    cloud_init();
    snprintf(url, sizeof(url), "%s/api/bind/start", app_cloud_base_url());

    curl = curl_easy_init();
    if (curl == NULL) {
        return CLOUD_ERR_HTTP;
    }
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, "Expect:");

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, "{}");
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, 2L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 20L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    rc = curl_easy_perform(curl);
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(curl);
    curl_slist_free_all(headers);

    if (rc != CURLE_OK || status < 200 || status >= 300) {
        printf("[Cloud] 申请绑定 token 失败（HTTP %ld）\n", status);
        free(chunk.memory);
        return CLOUD_ERR_HTTP;
    }

    root = cJSON_Parse(chunk.memory != NULL ? chunk.memory : "");
    free(chunk.memory);
    if (root == NULL) {
        return CLOUD_ERR_JSON;
    }

    item = cJSON_GetObjectItem(root, "bind_url");
    if (!cJSON_IsString(item) || item->valuestring == NULL) {
        cJSON_Delete(root);
        return CLOUD_ERR_JSON;
    }
    strncpy(url_out, item->valuestring, url_cap - 1);
    url_out[url_cap - 1] = '\0';

    item = cJSON_GetObjectItem(root, "token");
    if (!cJSON_IsString(item) || item->valuestring == NULL) {
        cJSON_Delete(root);
        return CLOUD_ERR_JSON;
    }
    strncpy(token_out, item->valuestring, token_cap - 1);
    token_out[token_cap - 1] = '\0';

    cJSON_Delete(root);
    ret = CLOUD_OK;
    return ret;
}

/* ---------- 文字转语音（开场白） ---------- */

int cloud_tts_text(const char *text, uint8_t **wav, size_t *wav_len)
{
    CURL *curl;
    CURLcode rc;
    struct mem_chunk chunk = { NULL, 0 };
    struct curl_slist *headers = NULL;
    cJSON *root = NULL;
    cJSON *item;
    char url[256];
    char *body = NULL;
    unsigned char *out = NULL;
    size_t body_cap;
    size_t out_len = 0;
    size_t b64_len;
    long status = 0;
    int b64_rc;

    if (wav == NULL || wav_len == NULL) {
        return CLOUD_ERR_NOMEM;
    }
    *wav = NULL;
    *wav_len = 0;

    if (!g_initialized) {
        cloud_init();
    }
    if (text == NULL || text[0] == '\0') {
        return CLOUD_ERR_HTTP;
    }

    snprintf(url, sizeof(url), "%s/api/test/tts", app_cloud_base_url());

    /* 手拼 JSON：调用方传入的是固定模板（岗位名里没有引号 / 反斜杠），
     * 不需要通用转义 —— 同 cloud_send_audio 的取舍。 */
    body_cap = strlen(text) * 2 + 64;
    body = malloc(body_cap);
    if (body == NULL) {
        return CLOUD_ERR_NOMEM;
    }
    snprintf(body, body_cap, "{\"text\":\"%s\"}", text);

    curl = curl_easy_init();
    if (curl == NULL) {
        free(body);
        return CLOUD_ERR_NOMEM;
    }

    headers = curl_slist_append(headers, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    rc = curl_easy_perform(curl);
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(curl);
    curl_slist_free_all(headers);
    free(body);

    if (rc != CURLE_OK || status < 200 || status >= 300) {
        free(chunk.memory);
        return CLOUD_ERR_HTTP;
    }

    root = cJSON_Parse(chunk.memory != NULL ? chunk.memory : "");
    free(chunk.memory);
    chunk.memory = NULL;
    if (root == NULL) {
        return CLOUD_ERR_JSON;
    }

    item = cJSON_GetObjectItem(root, "audio");
    if (!cJSON_IsString(item) || item->valuestring == NULL
        || item->valuestring[0] == '\0') {
        cJSON_Delete(root);
        return CLOUD_ERR_EMPTY_TTS;
    }

    b64_len = strlen(item->valuestring);
    /* 先探解码后长度，再分配（同 cloud_parse_response 的写法） */
    b64_rc = mbedtls_base64_decode(NULL, 0, &out_len,
                                   (const unsigned char *)item->valuestring, b64_len);
    if (b64_rc != 0 && b64_rc != MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL) {
        cJSON_Delete(root);
        return CLOUD_ERR_BAD_AUDIO;
    }
    if (out_len < 60) {   /* 44 字节头 + 至少一点数据 */
        cJSON_Delete(root);
        return CLOUD_ERR_BAD_AUDIO;
    }

    out = malloc(out_len);
    if (out == NULL) {
        cJSON_Delete(root);
        return CLOUD_ERR_NOMEM;
    }
    b64_rc = mbedtls_base64_decode(out, out_len, &out_len,
                                   (const unsigned char *)item->valuestring, b64_len);
    cJSON_Delete(root);

    if (b64_rc != 0) {
        free(out);
        return CLOUD_ERR_BAD_AUDIO;
    }
    if (out_len < 44 || memcmp(out, "RIFF", 4) != 0 ||
        memcmp(out + 8, "WAVE", 4) != 0) {
        printf("[Cloud] TTS 音频解码后不是 WAV\n");
        free(out);
        return CLOUD_ERR_BAD_AUDIO;
    }

    *wav = out;
    *wav_len = out_len;
    return CLOUD_OK;
}

/* ---------- 舍弃会话 ---------- */

/*
 * 只向工作线程暴露（主线程不得调用）—— 同本文件其它网络函数：
 * libcurl 的阻塞调用 + 大栈要求都只在 worker 线程里成立，见 main.c 顶部注释。
 */
int cloud_discard_session(const char *session_id)
{
    CURL *curl;
    CURLcode rc;
    struct mem_chunk chunk = { NULL, 0 };
    long status = 0;
    char url[256];

    if (!g_initialized) {
        cloud_init();
    }
    if (session_id == NULL || session_id[0] == '\0') {
        return CLOUD_ERR_HTTP;
    }

    snprintf(url, sizeof(url), "%s/api/sessions/%s",
             app_cloud_base_url(), session_id);

    curl = curl_easy_init();
    if (curl == NULL) {
        return CLOUD_ERR_NOMEM;
    }

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "DELETE");
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    rc = curl_easy_perform(curl);
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(curl);
    free(chunk.memory);

    if (rc != CURLE_OK) {
        return CLOUD_ERR_HTTP;
    }
    if (status < 200 || status >= 300) {
        return CLOUD_ERR_HTTP;
    }
    return CLOUD_OK;
}

/* ---------- 健康检查 ---------- */

int cloud_health_check(void)
{
    CURL *curl;
    CURLcode res;
    struct mem_chunk chunk;
    long status = 0;
    int ret = CLOUD_ERR_HTTP;

    cloud_init();

    chunk.memory = malloc(1);
    if (chunk.memory == NULL) {
        return CLOUD_ERR_NOMEM;
    }
    chunk.size = 0;

    curl = curl_easy_init();
    if (curl == NULL) {
        free(chunk.memory);
        return CLOUD_ERR_HTTP;
    }

    curl_easy_setopt(curl, CURLOPT_URL, g_url_health);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 5L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 15L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    res = curl_easy_perform(curl);
    if (res == CURLE_OK) {
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
        if (status >= 200 && status < 300) {
            ret = CLOUD_OK;
        }
    } else {
        printf("[Cloud] 健康检查失败: %s\n", curl_easy_strerror(res));
    }

    curl_easy_cleanup(curl);
    free(chunk.memory);

    printf("[Cloud] 健康检查 HTTP %ld -> %s\n", status,
           ret == CLOUD_OK ? "云端在线" : "云端不可达");
    return ret;
}

/* ---------- 响应解析 ---------- */

/* 从 JSON 里取字符串字段并复制一份堆内存；字段缺失返回 NULL（不算错误） */
static char *dup_string_field(const cJSON *root, const char *name)
{
    const cJSON *item = cJSON_GetObjectItem(root, name);
    size_t len;
    char *out;

    if (!cJSON_IsString(item) || item->valuestring == NULL) {
        return NULL;
    }

    len = strlen(item->valuestring);
    out = malloc(len + 1);
    if (out == NULL) {
        return NULL;
    }

    memcpy(out, item->valuestring, len + 1);
    return out;
}

/*
 * 失败时统一从这里返回：释放已分配字段并把 resp 归零，
 * 保证调用者无论成败都可以安全地调 cloud_response_free()，
 * 也保证错误路径不会留下半成品结构体。
 */
static int parse_fail(cloud_response_t *resp, int err)
{
    free(resp->text);
    free(resp->user_text);
    free(resp->tts_wav);
    memset(resp, 0, sizeof(*resp));
    return err;
}

int cloud_parse_response(const char *body, size_t len, cloud_response_t *resp)
{
    cJSON *root;
    const cJSON *item;
    size_t b64_len;
    size_t wav_len = 0;
    unsigned char *wav;
    int rc;

    if (body == NULL || resp == NULL || len == 0) {
        return CLOUD_ERR_JSON;
    }

    root = cJSON_ParseWithLength(body, len);
    if (root == NULL) {
        printf("[Cloud] 响应不是合法 JSON\n");
        return CLOUD_ERR_JSON;
    }

    /* session_id / next_action 是定长字段，直接拷进结构体 */
    item = cJSON_GetObjectItem(root, "session_id");
    if (cJSON_IsString(item) && item->valuestring != NULL) {
        strncpy(resp->session_id, item->valuestring,
                sizeof(resp->session_id) - 1);
        resp->session_id[sizeof(resp->session_id) - 1] = '\0';
    }

    item = cJSON_GetObjectItem(root, "next_action");
    if (cJSON_IsString(item) && item->valuestring != NULL) {
        strncpy(resp->next_action, item->valuestring,
                sizeof(resp->next_action) - 1);
        resp->next_action[sizeof(resp->next_action) - 1] = '\0';
    }

    resp->text = dup_string_field(root, "text");
    resp->user_text = dup_string_field(root, "user_text");

    /*
     * 防线 2：tts_audio 必须存在、是字符串、且非空。
     *
     * 云端在缺 MIMO_API_KEY 时会返回 HTTP 200 但 tts_audio 为空串，
     * 若这里放过，端侧会一路"成功"到播放环节却没有声音——演示时最难查。
     */
    item = cJSON_GetObjectItem(root, "tts_audio");
    if (!cJSON_IsString(item) || item->valuestring == NULL ||
        item->valuestring[0] == '\0') {
        /* text 里通常有云端给的兜底文案，打到串口便于定位 */
        printf("[Cloud] 响应缺少 tts_audio（云端可能未配置 API key）: %s\n",
               resp->text ? resp->text : "(无 text)");
        cJSON_Delete(root);
        return parse_fail(resp, CLOUD_ERR_EMPTY_TTS);
    }

    b64_len = strlen(item->valuestring);

    /* 先探解码后长度，再分配：mbedtls 在缓冲不足时回填所需大小 */
    rc = mbedtls_base64_decode(NULL, 0, &wav_len,
                               (const unsigned char *)item->valuestring, b64_len);
    if (rc != 0 && rc != MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL) {
        printf("[Cloud] tts_audio 不是合法 base64\n");
        cJSON_Delete(root);
        return parse_fail(resp, CLOUD_ERR_BAD_AUDIO);
    }

    if (wav_len < 60) {  /* 44 字节头 + 至少一点数据 */
        cJSON_Delete(root);
        return parse_fail(resp, CLOUD_ERR_BAD_AUDIO);
    }

    wav = malloc(wav_len);
    if (wav == NULL) {
        cJSON_Delete(root);
        return parse_fail(resp, CLOUD_ERR_NOMEM);
    }

    rc = mbedtls_base64_decode(wav, wav_len, &wav_len,
                               (const unsigned char *)item->valuestring, b64_len);
    cJSON_Delete(root);  /* 后续不再需要 JSON 树，尽早释放 */

    if (rc != 0) {
        free(wav);
        return parse_fail(resp, CLOUD_ERR_BAD_AUDIO);
    }

    /*
     * 防线 3：解码后必须是 WAV。
     * 云端异常时 tts_audio 里可能是错误文本或 HTML，直接送播放器会放出噪声。
     */
    if (wav_len < 44 || memcmp(wav, "RIFF", 4) != 0 ||
        memcmp(wav + 8, "WAVE", 4) != 0) {
        printf("[Cloud] tts_audio 解码后不是 WAV\n");
        free(wav);
        return parse_fail(resp, CLOUD_ERR_BAD_AUDIO);
    }

    resp->tts_wav = wav;
    resp->tts_wav_len = wav_len;

    return CLOUD_OK;
}

/* ---------- 主请求 ---------- */

int cloud_send_audio(const cloud_request_t *req, cloud_response_t *resp)
{
    CURL *curl = NULL;
    struct curl_slist *headers = NULL;
    struct mem_chunk chunk;
    CURLcode res;
    long status = 0;
    char *b64 = NULL;
    char *body = NULL;
    size_t b64_cap;
    size_t b64_len = 0;
    size_t body_cap;
    const char *sid;
    int ret;

    if (req == NULL || resp == NULL || req->wav == NULL || req->wav_len == 0) {
        return CLOUD_ERR_JSON;
    }

    cloud_init();

    memset(resp, 0, sizeof(*resp));
    chunk.memory = malloc(1);
    if (chunk.memory == NULL) {
        return CLOUD_ERR_NOMEM;
    }
    chunk.size = 0;

    /*
     * base64 编码。mbedtls 会在末尾写 '\0'，所以容量要 +1。
     * 用 mbedtls 而不是 apps/netutils/codecs：后者需要 CONFIG_CODECS_BASE64，
     * 而该配置在板级 defconfig 里没开，且 defconfig 不在本仓库内。
     */
    b64_cap = 4 * ((req->wav_len + 2) / 3) + 1;
    b64 = malloc(b64_cap);
    if (b64 == NULL) {
        ret = CLOUD_ERR_NOMEM;
        goto out;
    }

    if (mbedtls_base64_encode((unsigned char *)b64, b64_cap, &b64_len,
                              req->wav, req->wav_len) != 0) {
        printf("[Cloud] 音频 base64 编码失败\n");
        ret = CLOUD_ERR_NOMEM;
        goto out;
    }

    /*
     * 手写拼 JSON，不用 cJSON_Print：后者会把 1MB 级的 base64 串再复制转义
     * 一遍，峰值内存翻倍。
     * 无需转义——session_id 是 uuid、role 是固定常量、base64 只含 A-Za-z0-9+/=。
     * history 恒为空数组：多轮上下文由云端按 session_id 维护。
     */
    sid = (req->session_id != NULL) ? req->session_id : "";
    body_cap = b64_len + strlen(sid) + strlen(req->role) +
               strlen(req->pressure) + strlen(req->state) +
               strlen(g_user_token) + 320;
    body = malloc(body_cap);
    if (body == NULL) {
        ret = CLOUD_ERR_NOMEM;
        goto out;
    }

    snprintf(body, body_cap,
             "{\"session_id\":\"%s\",\"audio\":\"%s\",\"audio_format\":\"wav\","
             "\"role\":\"%s\",\"pressure\":\"%s\",\"state\":\"%s\","
             "\"target_rounds\":%d,"
             "\"user_token\":\"%s\",\"history\":[]}",
             sid, b64, req->role, req->pressure, req->state,
             g_target_rounds, g_user_token);

    /* body 已拼好，立刻释放 base64 缓冲，降低峰值内存 */
    free(b64);
    b64 = NULL;

    curl = curl_easy_init();
    if (curl == NULL) {
        ret = CLOUD_ERR_HTTP;
        goto out;
    }

    /*
     * 两个头缺一不可：
     *   Content-Type  缺了 Flask 的 request.get_json() 返回 None，云端直接回
     *                 400「请求体不能为空」，很容易误判成音频格式问题
     *   Expect:       抑制 100-continue，否则 body 超过 1KB 时 curl 会先发
     *                 Expect 头等待应答，白等 1 秒甚至失败
     */
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, "Expect:");

    curl_easy_setopt(curl, CURLOPT_URL, g_url_interview);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&chunk);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    /* 云端要串行跑 ASR + LLM + TTS，实测可能十几秒，给足余量 */
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 120L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);

    /*
     * TLS 证书校验默认是打开的（libcurl 默认行为）。
     *
     * 注意：板级 rootfs 里没有任何 CA 根证书
     * （CONFIG_LIB_CURL_CA_PATH 默认 /etc/ssl/curl，该路径不存在），
     * 因此走 https:// 时校验必然失败。
     *
     * 两条出路 —— 优先前者：
     *   1. 在设备上放一份 CA bundle，并把 CURLOPT_CAINFO 指过去
     *   2. 显式打开 APP_AI_INTERVIEW_TLS_INSECURE 跳过校验
     *      （仅适用于连自己的服务，演示用；不要长期开着）
     *
     * 用 http:// 时这里完全没有影响。
     */
#if defined(CONFIG_APP_AI_INTERVIEW_TLS_INSECURE)
    printf("[Cloud] 警告: 已跳过 TLS 证书校验\n");
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);
#endif

    res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        printf("[Cloud] 上传失败: %s\n", curl_easy_strerror(res));
        resp->http_status = 0;
        ret = CLOUD_ERR_HTTP;
        goto out;
    }

    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    resp->http_status = status;

    /* 防线 1：HTTP 状态码 */
    if (status < 200 || status >= 300) {
        printf("[Cloud] 云端返回 HTTP %ld\n", status);
        ret = CLOUD_ERR_HTTP;
        goto out;
    }

    /* 防线 2、3 都在 cloud_parse_response 内，保持判定逻辑单点 */
    ret = cloud_parse_response(chunk.memory, chunk.size, resp);
    resp->http_status = status;

    if (ret == CLOUD_OK) {
        printf("[Cloud] 本轮成功: %u 字节 WAV, next_action=%s\n",
               (unsigned)resp->tts_wav_len,
               resp->next_action[0] ? resp->next_action : "?");
    }

out:
    if (headers != NULL) {
        curl_slist_free_all(headers);
    }
    if (curl != NULL) {
        curl_easy_cleanup(curl);
    }
    free(b64);
    free(body);
    free(chunk.memory);
    return ret;
}

/* ---------- 清理 ---------- */

void cloud_response_free(cloud_response_t *resp)
{
    if (resp == NULL) {
        return;
    }

    free(resp->text);
    free(resp->user_text);
    free(resp->tts_wav);

    memset(resp, 0, sizeof(*resp));
}

/* ==========================================================================
 * 边录边传（2026-11-10）
 *
 * 录音线程把 100ms 的 PCM 块推进环形缓冲；后台线程跑 libcurl，用
 * READFUNCTION 把缓冲喂给一个 **chunked POST**（/api/interview/stream）。
 * 录音结束置 eof → curl 发出结束块 → 云端处理并回包。
 *
 * 为什么能省时间：上传带宽实测（≈58KB/s）高于录音产生速度（16k 单声道
 * 32KB/s），录音说完时音频基本已经传完，整段上传的 ~20 秒从关键路径消失。
 *
 * 失败一律回落整段上传（cloud_send_audio），不改变原有重试/补送逻辑。
 * ========================================================================== */

#define STREAM_RING_BYTES   (256u * 1024u)
#define STREAM_THREAD_STACK (256u * 1024u)

struct cloud_stream {
    char url[192];
    char role_enc[192];
    char pressure_enc[64];
    char session_id[64];
    char user_token[128];
    int  target_rounds;

    uint8_t *ring;
    size_t ring_cap;
    size_t ring_head;
    size_t ring_tail;
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int eof;
    int aborted;
    int overflow;

    struct mem_chunk chunk;     /* 响应体（复用整段上传那套） */
    long status;
    CURLcode res;
    pthread_t tid;
    int thread_ok;
};

/* 请求头只能放 ASCII：中文角色/压力档做百分号编码（UTF-8 字节） */
static void url_encode(const char *in, char *out, size_t cap)
{
    static const char *hex = "0123456789ABCDEF";
    size_t o = 0;
    const unsigned char *p;

    if (in == NULL) {
        in = "";
    }
    for (p = (const unsigned char *)in; *p != '\0' && o + 3 < cap; p++) {
        if ((*p >= 'A' && *p <= 'Z') || (*p >= 'a' && *p <= 'z') ||
            (*p >= '0' && *p <= '9') ||
            *p == '-' || *p == '_' || *p == '.' || *p == '~') {
            out[o++] = (char)*p;
        } else {
            out[o++] = '%';
            out[o++] = hex[*p >> 4];
            out[o++] = hex[*p & 0x0F];
        }
    }
    out[o] = '\0';
}

/* curl 的 READFUNCTION：从环形缓冲取数据；取空且 eof → 返回 0（发结束块）。
 * 用户取消 → CURL_READFUNC_ABORT（连接直接断，云端不会处理半截音频）。 */
static size_t stream_read_cb(char *buf, size_t size, size_t nitems, void *ud)
{
    struct cloud_stream *s = (struct cloud_stream *)ud;
    size_t want = size * nitems;
    size_t got = 0;

    pthread_mutex_lock(&s->lock);
    for (;;) {
        size_t avail;

        if (s->aborted) {
            pthread_mutex_unlock(&s->lock);
            return CURL_READFUNC_ABORT;
        }

        avail = (s->ring_head + s->ring_cap - s->ring_tail) % s->ring_cap;
        if (avail > 0) {
            while (got < want && avail > 0) {
                buf[got++] = (char)s->ring[s->ring_tail];
                s->ring_tail = (s->ring_tail + 1) % s->ring_cap;
                avail--;
            }
            break;
        }
        if (s->eof) {
            break;
        }
        pthread_cond_wait(&s->cond, &s->lock);
    }
    pthread_mutex_unlock(&s->lock);
    return got;
}

static void *stream_thread(void *arg)
{
    struct cloud_stream *s = (struct cloud_stream *)arg;
    struct curl_slist *headers = NULL;
    CURL *curl;
    char h[320];

    curl = curl_easy_init();
    if (curl == NULL) {
        s->res = CURLE_FAILED_INIT;
        return NULL;
    }

    headers = curl_slist_append(headers, "Content-Type: application/octet-stream");
    headers = curl_slist_append(headers, "Expect:");
    snprintf(h, sizeof(h), "X-Session-Id: %s", s->session_id);
    headers = curl_slist_append(headers, h);
    snprintf(h, sizeof(h), "X-Role: %s", s->role_enc);
    headers = curl_slist_append(headers, h);
    snprintf(h, sizeof(h), "X-Pressure: %s", s->pressure_enc);
    headers = curl_slist_append(headers, h);
    snprintf(h, sizeof(h), "X-Target-Rounds: %d", s->target_rounds);
    headers = curl_slist_append(headers, h);
    if (s->user_token[0] != '\0') {
        snprintf(h, sizeof(h), "X-User-Token: %s", s->user_token);
        headers = curl_slist_append(headers, h);
    }

    curl_easy_setopt(curl, CURLOPT_URL, s->url);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_READFUNCTION, stream_read_cb);
    curl_easy_setopt(curl, CURLOPT_READDATA, s);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, -1L);  /* 未知长度 → chunked */
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_memory_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&s->chunk);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 180L);       /* 录音 30s + 云端处理 */
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
#if defined(CONFIG_APP_AI_INTERVIEW_TLS_INSECURE)
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);
#endif

    s->res = curl_easy_perform(curl);
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &s->status);
    curl_easy_cleanup(curl);
    curl_slist_free_all(headers);
    return NULL;
}

cloud_stream_t *cloud_stream_begin(const cloud_request_t *req)
{
    struct cloud_stream *s;
    pthread_attr_t attr;
    const char *tok;
    int rc;

    if (req == NULL || req->role == NULL || req->pressure == NULL) {
        return NULL;
    }
    cloud_init();

    s = calloc(1, sizeof(*s));
    if (s == NULL) {
        return NULL;
    }
    s->ring = malloc(STREAM_RING_BYTES);
    s->chunk.memory = malloc(1);
    if (s->ring == NULL || s->chunk.memory == NULL) {
        free(s->ring);
        free(s->chunk.memory);
        free(s);
        return NULL;
    }
    s->ring_cap = STREAM_RING_BYTES;
    s->chunk.size = 0;
    pthread_mutex_init(&s->lock, NULL);
    pthread_cond_init(&s->cond, NULL);

    snprintf(s->url, sizeof(s->url), "%s/api/interview/stream",
             app_cloud_base_url());
    url_encode(req->role, s->role_enc, sizeof(s->role_enc));
    url_encode(req->pressure, s->pressure_enc, sizeof(s->pressure_enc));
    if (req->session_id != NULL) {
        strncpy(s->session_id, req->session_id, sizeof(s->session_id) - 1);
    }
    tok = cloud_user_token();
    if (tok != NULL) {
        strncpy(s->user_token, tok, sizeof(s->user_token) - 1);
    }
    s->target_rounds = cloud_target_rounds();

    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, STREAM_THREAD_STACK);
    rc = pthread_create(&s->tid, &attr, stream_thread, s);
    pthread_attr_destroy(&attr);
    if (rc != 0) {
        printf("[Cloud] 边录边传线程创建失败 (%d)，回退整段上传\n", rc);
        pthread_mutex_destroy(&s->lock);
        pthread_cond_destroy(&s->cond);
        free(s->ring);
        free(s->chunk.memory);
        free(s);
        return NULL;
    }
    s->thread_ok = 1;
    return s;
}

int cloud_stream_feed(cloud_stream_t *s, const uint8_t *pcm, size_t len)
{
    size_t head;
    size_t tail;
    size_t space;
    size_t i;

    if (s == NULL || pcm == NULL || len == 0) {
        return -1;
    }

    pthread_mutex_lock(&s->lock);
    if (s->aborted || s->eof) {
        pthread_mutex_unlock(&s->lock);
        return -1;
    }
    head = s->ring_head;
    tail = s->ring_tail;
    space = s->ring_cap - ((head + s->ring_cap - tail) % s->ring_cap) - 1;
    if (len > space) {
        /* 缓冲满 = 上传跟不上录音（网络过慢）—— 标记失败，让调用方回退 */
        s->overflow = 1;
        pthread_mutex_unlock(&s->lock);
        printf("[Cloud] 边录边传缓冲满（网络过慢），将回退整段上传\n");
        return -1;
    }
    for (i = 0; i < len; i++) {
        s->ring[head] = pcm[i];
        head = (head + 1) % s->ring_cap;
    }
    s->ring_head = head;
    pthread_cond_signal(&s->cond);
    pthread_mutex_unlock(&s->lock);
    return 0;
}

static void stream_destroy(cloud_stream_t *s)
{
    pthread_mutex_destroy(&s->lock);
    pthread_cond_destroy(&s->cond);
    free(s->ring);
    free(s->chunk.memory);
    free(s);
}

int cloud_stream_finish(cloud_stream_t *s, cloud_response_t *resp)
{
    int ret;

    if (s == NULL || resp == NULL) {
        return CLOUD_ERR_HTTP;
    }

    memset(resp, 0, sizeof(*resp));

    pthread_mutex_lock(&s->lock);
    s->eof = 1;
    pthread_cond_broadcast(&s->cond);
    pthread_mutex_unlock(&s->lock);

    if (s->thread_ok) {
        pthread_join(s->tid, NULL);
    }

    if (s->overflow) {
        ret = CLOUD_ERR_HTTP;           /* 调用方回退整段上传 */
    } else if (s->res != CURLE_OK) {
        printf("[Cloud] 边录边传失败: %s（回退整段上传）\n",
               curl_easy_strerror(s->res));
        resp->http_status = 0;
        ret = CLOUD_ERR_HTTP;
    } else if (s->status < 200 || s->status >= 300) {
        printf("[Cloud] 流式端点返回 HTTP %ld\n", s->status);
        resp->http_status = s->status;
        ret = CLOUD_ERR_HTTP;
    } else {
        ret = cloud_parse_response(s->chunk.memory != NULL ? s->chunk.memory : "",
                                   s->chunk.size, resp);
        resp->http_status = s->status;
    }

    stream_destroy(s);
    return ret;
}

void cloud_stream_abort(cloud_stream_t *s)
{
    if (s == NULL) {
        return;
    }

    pthread_mutex_lock(&s->lock);
    s->aborted = 1;
    pthread_cond_broadcast(&s->cond);
    pthread_mutex_unlock(&s->lock);

    if (s->thread_ok) {
        pthread_join(s->tid, NULL);
    }
    stream_destroy(s);
}
