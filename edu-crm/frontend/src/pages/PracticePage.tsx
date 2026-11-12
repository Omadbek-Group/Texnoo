import { useEffect, useState } from 'react';
import axios from 'axios';

interface Question {
  id: number;
  text: string;
  options: string[];
}

interface CheckResult {
  score: number;
  total: number;
  results: { id: number; correct: boolean; answer: number }[];
}

export function PracticePage() {
  const [subject, setSubject] = useState('');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<CheckResult | null>(null);
  const [error, setError] = useState('');
  // Imtihon rejimi: vaqt tugaguncha sahifani tark etish ogohlantiriladi, vaqt tugasa avtomatik topshiriladi.
  const EXAM_MINUTES = 30;
  const [examEndsAt, setExamEndsAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const examActive = examEndsAt !== null && !result;

  useEffect(() => {
    if (!examActive) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [examActive]);

  useEffect(() => {
    if (examEndsAt === null || result) return;
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= examEndsAt) submit();
    }, 1000);
    return () => clearInterval(timer);
  }, [examEndsAt, result, answers]);

  const remainingSec = examEndsAt ? Math.max(0, Math.ceil((examEndsAt - now) / 1000)) : 0;

  function startExam() {
    setAnswers({});
    setResult(null);
    setNow(Date.now());
    setExamEndsAt(Date.now() + EXAM_MINUTES * 60 * 1000);
  }

  useEffect(() => {
    axios
      .get('/api/practice/coding')
      .then(res => {
        setSubject(res.data.subject);
        setQuestions(res.data.questions);
      })
      .catch(err => setError(err.response?.data?.error || 'Savollarni yuklab bo\'lmadi.'));
  }, []);

  async function submit() {
    setError('');
    try {
      const res = await axios.post('/api/practice/coding/check', { answers });
      setResult(res.data);
      setExamEndsAt(null);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Tekshirib bo\'lmadi.');
    }
  }

  function reset() {
    setAnswers({});
    setResult(null);
    setExamEndsAt(null);
  }

  const allAnswered = questions.length > 0 && questions.every(q => answers[q.id] !== undefined);

  return (
    <section>
      <div className="page-heading">
        <h1>Mashq testi</h1>
        <p className="subtitle">{subject}</p>
      </div>
      {error && <div className="alert">{error}</div>}

      {examActive && (
        <div className="alert alert-info">
          Imtihon davom etmoqda. Qolgan vaqt: <strong>{Math.floor(remainingSec / 60)}:{String(remainingSec % 60).padStart(2, '0')}</strong>.
          Vaqt tugaguncha sahifadan chiqmang.
        </div>
      )}

      {questions.map((q, index) => {
        const check = result?.results.find(r => r.id === q.id);
        return (
          <div key={q.id} className="card quiz-question">
            <strong>{index + 1}. {q.text}</strong>
            <div className="quiz-options">
              {q.options.map((option, optionIndex) => {
                const selected = answers[q.id] === optionIndex;
                const isRight = !!check && check.answer === optionIndex;
                const isWrong = !!check && selected && !check.correct;
                return (
                  <label
                    key={optionIndex}
                    className={`quiz-option${selected ? ' is-selected' : ''}${isRight ? ' is-right' : ''}${isWrong ? ' is-wrong' : ''}`}
                  >
                    <input
                      type="radio"
                      name={`q${q.id}`}
                      checked={selected}
                      disabled={!!result}
                      onChange={() => setAnswers({ ...answers, [q.id]: optionIndex })}
                    />
                    {option}
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}

      {result ? (
        <div className="card quiz-result">
          <p>Natija: <strong>{result.score} / {result.total}</strong></p>
          <button type="button" className="outline-button" onClick={reset}>Qayta boshlash</button>
        </div>
      ) : examActive ? (
        <button type="button" className="primary-button" onClick={submit} disabled={!allAnswered}>
          Imtihonni topshirish
        </button>
      ) : (
        <button type="button" className="primary-button" onClick={startExam}>
          Imtihonni boshlash ({EXAM_MINUTES} daqiqa)
        </button>
      )}
    </section>
  );
}
