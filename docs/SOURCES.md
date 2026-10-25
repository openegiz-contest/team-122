# Источники и происхождение

## Основная модель v3

Воздушная сеть приложения теперь основана на Jia, Ma, Gao (2025), PLOS ONE, DOI https://doi.org/10.1371/journal.pone.0320326, CC BY 4.0: таблица 4, топология эквивалентной сети и характеристики вентиляторов раздела 4.1. CSV и исходный XML сохранены. Предыдущая формулировка «отдельное воспроизведение» ниже относится к истории v2. Метан, эффективное смешение и датчики из статьи не получены; происхождение каждой величины v3 указано в PARAMETERS.md и objects.json.

Ниже сохранён литературный контекст прежней версии. Он не подтверждает газовые параметры новой сети и не означает реализации алгоритмов этих статей.

Зависимость OpenEgiz Extended API: https://github.com/ertis-research/extended-api-for-eclipse-ditto, коммит b49663dea326854a2323423eaeab7e7f54d325a7. Загружается при запуске с проверкой SHA256; локальный кэш не распространяется. См. integration/vendor/ATTRIBUTION.md. Конфигурация OpenEgiz сохранена, изменён только способ получения того же build context.

1. OpenEgiz: https://github.com/aleka07/openegiz — снимок 8d60b6dffdfd153e7257ecf5921327920aaba03f, MIT и сторонние лицензии внутри upstream. Контракты: examples/mine/simulator.py, setup_twins.py; deploy/compose/init/mosquitto-source-connection.json; Grafana datasource и Telegraf config. Код транспортного примера не используется как наша предметная модель.
2. Liu et al. (2022). Efficient Graphical Algorithm of Sensor Distribution and Air Volume Reconstruction for a Smart Mine Ventilation Network. https://doi.org/10.3390/s22062096 — ограниченные измерения и восстановление потоков. Их алгоритм не реализован; используется собственное аналитическое решение малой сети.
3. Chinyadza et al. (2026). Integrating Artificial Intelligence into Ventilation on Demand: Current Practice and Future Promises. https://doi.org/10.3390/s26031042 — актуальность отказоустойчивости, резервных режимов и проверки.
4. Yang et al. (2026). A Missing Data Imputation Method for Gas Time Series Based on Spatio-Temporal Graph Attention Network—Echo State Network. https://doi.org/10.3390/s26103016 — пропуски и отличие восстановления истории от оперативного наблюдения. Метод статьи не воспроизводился.
5. Wang et al. (2026). Bridging data-driven fault diagnosis and ventilation physics through physics-consistent interpretability. https://doi.org/10.1016/j.engappai.2026.116168 — близкая работа; широкое заявление новизны требует содержательного сравнения.

Расчётные зависимости баланса и сопротивления сети согласованы с физическими принципами, изложенными в литературе. Численные параметры, топология, объёмы, источники, допуски, стоимости и экспериментальный порог определены нами для синтетического стенда. Они не извлечены из этих статей. Сторонние промышленные данные не включались.

## Проверка библиографии, 25 октября 2026

Названия и DOI четырёх статей сопоставлены с карточками издателей:

- [Liu et al., Sensors 22(6), 2096](https://www.mdpi.com/1424-8220/22/6/2096).
- [Chinyadza et al., Sensors 26(3), 1042](https://www.mdpi.com/1424-8220/26/3/1042).
- [Yang et al., Sensors 26(10), 3016](https://www.mdpi.com/1424-8220/26/10/3016).
- [Wang et al., Engineering Applications of Artificial Intelligence, 116168](https://www.sciencedirect.com/science/article/pii/S0952197626024528).

Эта проверка подтверждает библиографические сведения; она не является воспроизведением методов статей и не подтверждает параметры нашего участка.

Официальные документы конкурса: [Положение](https://openegiz-contest.github.io/ru/rules/), [окружение судьи](https://openegiz-contest.github.io/ru/environment/). Организационные требования следует сверять с этими страницами, а не с рекомендациями в плане доработок.

## Данные для отдельного воспроизведения

Jia, Ma, Gao (2025), PLOS ONE, DOI: https://doi.org/10.1371/journal.pone.0320326 . Использованы таблица 4 и характеристики раздела 4.1; CC BY 4.0. Полная атрибуция и происхождение: reference/ATTRIBUTION.md. Источник не содержит калибровки метанового блока нашего стенда.
