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
      <div className="page-heading">
        <h1>Mashq testi</h1>
        <p className="subtitle">{subject}</p>
      </div>
      {error && <div className="alert">{error}</div>}

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
      ) : (
        <button type="button" className="primary-button" onClick={submit} disabled={!allAnswered}>
          Tekshirish
        </button>
      )}
    </section>
  );
}
