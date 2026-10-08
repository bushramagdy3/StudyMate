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

function QuizQuestions({ quiz, progress, isSubmitting, onProgressChange, onSubmit }) {
  const current = progress?.current ?? 0
  const answers = progress?.answers ?? quiz.questions.map(() => null)
  const question = quiz.questions[current]
  const isLast = current === quiz.questions.length - 1
  const chosen = answers[current]

  function setAnswer(value) {
    onProgressChange({
      current,
      answers: answers.map((answer, index) => (index === current ? value : answer)),
    })
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
      <div className="quiz-question-workspace">
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
      </div>

      <footer className="quiz-actions">
        {current > 0 && (
          <PopupButton
            disabled={isSubmitting}
            onClick={() => onProgressChange({ current: current - 1, answers })}
          >
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
          <PopupButton
            disabled={!isAnswered(chosen)}
            onClick={() => onProgressChange({ current: current + 1, answers })}
          >
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
      <div className="quiz-results-workspace">
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
                <div className="quiz-review-heading">
                  <span className="quiz-review-status">
                    {item.correct ? 'Correct' : 'Incorrect'}
                  </span>
                  <span className="quiz-review-number">Question {item.index + 1}</span>
                </div>
                <p className="quiz-review-question">
                  <span className="quiz-review-mark">{item.correct ? '✓' : '✗'}</span>
                  {item.question}
                </p>
                {item.kind === 'text' ? (
                  <>
                    <div className="quiz-review-line student-answer">
                      <strong>Your answer</strong>
                      <AnswerText code={item.code_answer}>{item.answer_text || 'none'}</AnswerText>
                    </div>
                    {item.feedback && <p className="quiz-grader-feedback">{item.feedback}</p>}
                    <div className="quiz-review-line correct-answer">
                      <strong>Model answer</strong>
                      <AnswerText code={item.code_answer}>{item.expected_answer}</AnswerText>
                    </div>
                  </>
                ) : (
                  <div className="quiz-review-answers">
                    <div className="quiz-review-line student-answer">
                      <strong>Your answer</strong>
                      <span>{item.chosen_index === null ? 'No answer' : item.options[item.chosen_index]}</span>
                    </div>
                    <div className="quiz-review-line correct-answer">
                      <strong>Correct answer</strong>
                      <span>{item.options[item.correct_index]}</span>
                    </div>
                  </div>
                )}
                {item.explanation && (
                  <aside className="quiz-explanation">
                    <strong>Why this matters</strong>
                    <span>{item.explanation}</span>
                  </aside>
                )}
              </li>
            ))}
          </ol>
        </section>
        </div>
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
  progress,
  onProgressChange,
  retryLabel = 'Try again',
  onSubmit,
}) {
  if (!status) return null

  const contentMode = status === 'loading' || status === 'error'
    ? 'state'
    : status === 'results'
      ? 'results'
      : 'taking'

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
          <PopupButton onClick={onRetry}>{retryLabel}</PopupButton>
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
        progress={progress}
        isSubmitting={status === 'submitting'}
        onProgressChange={onProgressChange}
        onSubmit={onSubmit}
      />
    )
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className={`about-popup topic-summary-popup quiz-popup quiz-popup--${contentMode}`}
        style={{ backgroundImage: `url(${popupPanel})` }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="quiz-title"
      >
        <button className="about-close" type="button" onClick={onClose} aria-label="Close quiz">
          <img src={closeButton} alt="" />
        </button>

        <div className={`about-popup-content quiz-content quiz-content--${contentMode}`}>
          {content}
        </div>
      </section>
    </div>
  )
}
