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
    } catch (err: any) {
      setError(err.response?.data?.error || 'Tekshirib bo\'lmadi.');
    }
  }

  function reset() {
    setAnswers({});
    setResult(null);
  }

  const allAnswered = questions.length > 0 && questions.every(q => answers[q.id] !== undefined);

  return (
    <section>
      <h1>Mashq testi</h1>
      <p>{subject}</p>
      {error && <div className="alert">{error}</div>}

      {questions.map((q, index) => {
        const check = result?.results.find(r => r.id === q.id);
        return (
          <div key={q.id} className="card" style={{ marginBottom: 12 }}>
            <strong>{index + 1}. {q.text}</strong>
            <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
              {q.options.map((option, optionIndex) => {
                const selected = answers[q.id] === optionIndex;
                const isRight = check && check.answer === optionIndex;
                const isWrong = check && selected && !check.correct;
                return (
                  <label
                    key={optionIndex}
                    style={{
                      padding: '6px 10px',
                      borderRadius: 6,
                      border: '1px solid',
                      borderColor: isRight ? '#16a34a' : isWrong ? '#dc2626' : 'currentColor',
                      cursor: result ? 'default' : 'pointer'
                    }}
                  >
                    <input
                      type="radio"
                      name={`q${q.id}`}
                      checked={selected}
                      disabled={!!result}
                      onChange={() => setAnswers({ ...answers, [q.id]: optionIndex })}
                      style={{ marginRight: 8 }}
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
        <div className="card">
          <p>Natija: <strong>{result.score} / {result.total}</strong></p>
          <button type="button" onClick={reset}>Qayta boshlash</button>
        </div>
      ) : (
        <button type="button" onClick={submit} disabled={!allAnswered}>
          Tekshirish
        </button>
      )}
    </section>
  );
}
