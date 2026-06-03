# 📈 Real-Time Stock Monitor
## مشروع نظم التشغيل — جامعي متقدم

---

## 🎯 وصف المشروع
برنامج مراقبة الأسهم في الوقت الفعلي — يُحاكي نظام تداول حقيقي باستخدام
مفاهيم نظم التشغيل المتقدمة: Threads, Mutex, Synchronization.

---

## ⚙️ المفاهيم المستخدمة

| المفهوم | كيف طُبِّق في المشروع |
|---|---|
| **Threads** | 4 خيوط تعمل بالتوازي |
| **Mutex / Lock** | `stock_lock`, `alert_lock`, `portfolio_lock` |
| **Shared Resources** | بيانات الأسعار تُقرأ من كل الخيوط |
| **Synchronization** | كل Thread يقفل وينفذ ويطلق |
| **Race Condition** | تجريبي: عداد بدون Lock وآخر بـ Mutex |
| **Thread-safe Queue** | `queue.Queue()` لأحداث الـ Console |

---

## 🧵 الخيوط (Threads)

### Thread 1 — StockUpdaterThread
- يُحدِّث أسعار 6 أسهم كل ثانية
- يستخدم `stock_lock` (Mutex) لحماية البيانات المشتركة

### Thread 2 — AlertCheckerThread
- يراقب الأسعار كل ثانيتين
- يستخدم `stock_lock` للقراءة ثم `alert_lock` للكتابة
- لا deadlock لأنه يُطلق أحدهما قبل الإمساك بالآخر

### Thread 3 — PortfolioThread
- يحسب قيمة المحفظة كل 1.5 ثانية
- يستخدم `portfolio_lock` + `stock_lock`

### Thread 4 — RaceConditionDemo
- خيطان يزيدان عداداً 1000 مرة
- بدون Mutex → النتيجة أقل من 2000 (تلوث البيانات!)
- مع Mutex → النتيجة دائماً 2000

---

## 🖥️ الواجهات الرسومية (GUI)

1. **Dashboard** — بطاقات مباشرة لكل سهم
2. **Live Chart** — رسم بياني حي بـ matplotlib
3. **Portfolio** — إدارة المحفظة وحساب القيمة
4. **Alerts** — تنبيهات تجاوز الحد
5. **Race Condition** — عرض عملي للخطأ والحل
6. **Thread Monitor** — جدول الخيوط + Console Log

---

## 🚀 تشغيل المشروع

```bash
pip install matplotlib
python stock_monitor.py
```

---

## 👥 توزيع العمل المقترح (4-5 أشخاص)

| الشخص | المسؤولية |
|---|---|
| 1 | Thread 1 + stock_lock |
| 2 | Thread 2 + AlertChecker |
| 3 | Thread 3 + Portfolio UI |
| 4 | Race Condition Demo + Thread Monitor |
| 5 | Chart Tab + Dashboard UI |

---

## 📊 التقييم — كيف يحقق المشروع الدرجات

| العنصر | الدرجة | كيف تحققه |
|---|---|---|
| الفكرة | 10 | فكرة واقعية ومعقدة |
| جودة GUI | 10 | واجهة احترافية multi-tab |
| استخدام Threads | 20 | 4 threads حقيقية |
| Synchronization | 20 | 3 locks مختلفة |
| جودة الكود | 10 | منظم ومعلَّق |
| التقرير | 10 | README كامل |
| العرض | 20 | demo Race Condition مرئي |
