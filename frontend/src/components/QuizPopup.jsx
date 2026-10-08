import { useState } from 'react'
import closeButton from '../assets/about/close-button.png'
import popupPanel from '../assets/about/popup-panel.png'
import loadingIcon from '../assets/generated-icons/outline-loading.gif'

const OPTION_LETTERS = ['A', 'B', 'C', 'D']

// An option picked, or something typed (not just spaces).
function isAnswered(answer) {
  return typeof answer === 'number' || (typeof answer === 'string' && answer.trim() !== '')
}

// Code keeps its line breaks and spacing; other text wraps normally.
function AnswerText({ code, children }) {
  return code ? <pre className="quiz-code">{children}</pre> : <span>{children}</span>
}

function PopupButton({ children, disabled = false, onClick }) {
  return (
    <button
      className="quiz-action-button"
      disabled={disabled}
      type="button"
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function QuizQuestions({ quiz, isSubmitting, onSubmit }) {
  const [current, setCurrent] = useState(0)
  const [answers, setAnswers] = useState(() => quiz.questions.map(() => null))
  const question = quiz.questions[current]
  const isLast = current === quiz.questions.length - 1
  const chosen = answers[current]

  function setAnswer(value) {
    setAnswers((previous) =>
      previous.map((answer, index) => (index === current ? value : answer)),
    )
  }

  function typeInCodeBox(event) {
    // Tab indents inside a code answer instead of leaving the box.
    if (event.key !== 'Tab' || !question.code_answer) {
      return
    }

    event.preventDefault()
    const box = event.target
    const { selectionStart, selectionEnd, value } = box
    setAnswer(`${value.slice(0, selectionStart)}  ${value.slice(selectionEnd)}`)
    requestAnimationFrame(() => {
      box.selectionStart = selectionStart + 2
      box.selectionEnd = selectionStart + 2
    })
  }

  function submit() {
    onSubmit(answers.map((answer) => (typeof answer === 'string' ? answer.trim() : answer)))
  }

  return (
    <>
      <header className="quiz-header">
        <h2 id="quiz-title">Quiz</h2>
        <div className="quiz-context">
          <span className="quiz-progress">Question {current + 1} / {quiz.questions.length}</span>
          <span className="quiz-topic">{question.topic_title}</span>
        </div>
      </header>

      <div className="quiz-question-panel">
        {/* key: each question pops in like the panels. */}
        <p className="quiz-question" key={question.index}>
          {question.question}
        </p>
        {question.kind === 'text' ? (
          <textarea
            className={question.code_answer ? 'quiz-answer-input code' : 'quiz-answer-input'}
            // key: a fresh box for each question.
            key={`answer-${question.index}`}
            aria-label="Your answer"
            disabled={isSubmitting}
            placeholder={question.code_answer ? 'Write your code…' : 'Type your answer…'}
            rows={question.code_answer ? 6 : 3}
            spellCheck={!question.code_answer}
            value={chosen ?? ''}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={typeInCodeBox}
          />
        ) : (
          <div className="quiz-options" role="radiogroup" aria-labelledby="quiz-title">
            {question.options.map((option, optionIndex) => (
              <button
                className={chosen === optionIndex ? 'quiz-option selected' : 'quiz-option'}
                disabled={isSubmitting}
                key={`${question.index}-${optionIndex}`}
                role="radio"
                aria-checked={chosen === optionIndex}
                type="button"
                onClick={() => setAnswer(optionIndex)}
              >
                <span className="quiz-option-letter">{OPTION_LETTERS[optionIndex]}</span>
                <span>{option}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <footer className="quiz-actions">
        {current > 0 && (
          <PopupButton disabled={isSubmitting} onClick={() => setCurrent(current - 1)}>
            Back
          </PopupButton>
        )}
        {isLast ? (
          <PopupButton
            disabled={isSubmitting || !answers.every(isAnswered)}
            onClick={submit}
          >
            {isSubmitting ? 'Marking…' : 'Submit'}
          </PopupButton>
        ) : (
          <PopupButton disabled={!isAnswered(chosen)} onClick={() => setCurrent(current + 1)}>
            Next
          </PopupButton>
        )}
      </footer>
    </>
  )
}

function QuizResults({ result, onRetake, onNewQuiz, onClose }) {
  return (
    <>
      <header className="quiz-header">
        <h2 id="quiz-title">Quiz results</h2>
        <p className="quiz-score">
          {result.score} / {result.total} correct
        </p>
      </header>

      <div className="quiz-results-panel" tabIndex="0">
        <p className="quiz-feedback">{result.feedback}</p>

        {result.topics_to_improve.length > 0 && (
          <section className="lecture-summary-section quiz-improve">
            <h3>Topics to improve on</h3>
            <ul>
              {result.topics_to_improve.map((topic) => (
                <li key={topic.index}>{topic.title}</li>
              ))}
            </ul>
          </section>
        )}

        <section className="lecture-summary-section quiz-review">
          <h3>Your answers</h3>
          <ol>
            {result.review.map((item) => (
              <li
                className={item.correct ? 'quiz-review-item correct' : 'quiz-review-item wrong'}
                key={item.index}
              >
                <p className="quiz-review-question">
                  <span className="quiz-review-mark">{item.correct ? '✓' : '✗'}</span>
                  {item.question}
                </p>
                {item.kind === 'text' ? (
                  <>
                    <div className="quiz-review-line">
                      Your answer:{' '}
                      <AnswerText code={item.code_answer}>{item.answer_text || 'none'}</AnswerText>
                    </div>
                    {item.feedback && <p className="quiz-grader-feedback">{item.feedback}</p>}
                    <div className="quiz-review-line">
                      Model answer:{' '}
                      <AnswerText code={item.code_answer}>{item.expected_answer}</AnswerText>
                    </div>
                  </>
                ) : (
                  <>
                    {!item.correct && (
                      <p>
                        Your answer:{' '}
                        {item.chosen_index === null ? 'none' : item.options[item.chosen_index]}
                      </p>
                    )}
                    <p>Correct answer: {item.options[item.correct_index]}</p>
                  </>
                )}
                {item.explanation && <p className="quiz-explanation">{item.explanation}</p>}
              </li>
            ))}
          </ol>
        </section>
      </div>

      <footer className="quiz-actions">
        <PopupButton onClick={onRetake}>Retake</PopupButton>
        <PopupButton onClick={onNewQuiz}>New questions</PopupButton>
        <PopupButton onClick={onClose}>Close</PopupButton>
      </footer>
    </>
  )
}

// The mini quiz, over the lecture. `status` is 'loading', 'taking',
// 'submitting', 'results' or 'error'.
export function QuizPopup({
  error,
  quiz,
  result,
  status,
  onClose,
  onNewQuiz,
  onRetake,
  onRetry,
  onSubmit,
}) {
  if (!status) return null

  let content
  if (status === 'loading') {
    content = (
      <div className="quiz-loading" role="status">
        <h2 id="quiz-title">Quiz</h2>
        <img src={loadingIcon} alt="" />
        <p>Regina is writing your quiz…</p>
      </div>
    )
  } else if (status === 'error') {
    content = (
      <div className="quiz-loading" role="alert">
        <h2 id="quiz-title">Quiz</h2>
        <p>{error || 'Something went wrong with the quiz.'}</p>
        <footer className="quiz-actions">
          <PopupButton onClick={onRetry}>Try again</PopupButton>
          <PopupButton onClick={onClose}>Close</PopupButton>
        </footer>
      </div>
    )
  } else if (status === 'results' && result) {
    content = (
      <QuizResults result={result} onRetake={onRetake} onNewQuiz={onNewQuiz} onClose={onClose} />
    )
  } else if (quiz) {
    content = (
      <QuizQuestions
        // A new or restarted quiz starts again from the first question, with no answers.
        key={quiz.attempt}
        quiz={quiz}
        isSubmitting={status === 'submitting'}
        onSubmit={onSubmit}
      />
    )
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="about-popup topic-summary-popup quiz-popup"
        style={{ backgroundImage: `url(${popupPanel})` }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="quiz-title"
      >
        <button className="about-close" type="button" onClick={onClose} aria-label="Close quiz">
          <img src={closeButton} alt="" />
        </button>

        <div className="about-popup-content quiz-content">{content}</div>
      </section>
    </div>
  )
}
