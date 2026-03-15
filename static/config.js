/** Локальная разработка: API на том же хосте */
window.MATRIX_API_BASE = '';

/**
 * CryptoCloud — постоянная страница оплаты (тестовый режим).
 * Задайте одну из переменных (если на сервере env не подхватывается):
 * — MATRIX_CRYPTOCLOUD_POS_LINK: полная ссылка, например https://pay.cryptocloud.plus/pos/nHFyGCeofCdjbV32
 * — MATRIX_CRYPTOCLOUD_POS_ID: только id страницы, например nHFyGCeofCdjbV32
 */
window.MATRIX_CRYPTOCLOUD_POS_LINK = window.MATRIX_CRYPTOCLOUD_POS_LINK || '';
window.MATRIX_CRYPTOCLOUD_POS_ID = window.MATRIX_CRYPTOCLOUD_POS_ID || '';
